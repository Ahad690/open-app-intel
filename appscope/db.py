"""Database layer for AppScope (§8).

SQLite by default (Postgres-compatible schema). Each user runs this locally;
nothing here ever talks to a central server. The schema includes the v1.1
``flow_anchors`` table that backs federated calibration.

Higher-stage methods (anchor fetch/merge, recalibration, estimate writes) are
added in later build stages; Stage 0 only needs ``bootstrap()`` to create the
full §8 schema.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

# --- §8 schema (SQLite default; Postgres-compatible) -------------------------

SCHEMA: str = """
CREATE TABLE IF NOT EXISTS apps (
  app_id TEXT PRIMARY KEY, platform TEXT NOT NULL, name TEXT, developer TEXT,
  category TEXT, country TEXT, price_usd REAL, is_free INTEGER,
  first_seen DATE, last_updated DATE
);

CREATE TABLE IF NOT EXISTS rank_history (
  app_id TEXT, country TEXT, list_type TEXT, category TEXT,
  rank INTEGER, captured_on DATE,
  PRIMARY KEY (app_id, country, list_type, category, captured_on)
);

CREATE TABLE IF NOT EXISTS install_buckets (        -- ANDROID ONLY (anchor source)
  app_id TEXT, min_installs INTEGER, real_installs INTEGER, captured_on DATE,
  PRIMARY KEY (app_id, captured_on)
);

-- NEW in v1.1: observed download-flow anchors (from install-bucket deltas).
-- 'source' distinguishes your own observations from pulled community ones.
CREATE TABLE IF NOT EXISTS flow_anchors (
  platform TEXT, category TEXT, country TEXT, list_type TEXT,
  rank INTEGER, observed_downloads INTEGER, window_days INTEGER,
  captured_on DATE, source TEXT,      -- 'local' | 'community'
  PRIMARY KEY (platform, category, country, list_type, rank, captured_on, source)
);

CREATE TABLE IF NOT EXISTS calibration (            -- fitted scale per segment
  platform TEXT, list_type TEXT, category TEXT, country TEXT,
  shape_a REAL NOT NULL, scale_b REAL, n_anchors INTEGER NOT NULL, updated_on DATE,
  PRIMARY KEY (platform, list_type, category, country)
);

CREATE TABLE IF NOT EXISTS estimates (
  app_id TEXT, country TEXT, captured_on DATE,
  downloads_point REAL, downloads_low REAL, downloads_high REAL,
  revenue_point REAL, confidence TEXT NOT NULL, method TEXT NOT NULL, flags TEXT,
  PRIMARY KEY (app_id, country, captured_on)
);

CREATE TABLE IF NOT EXISTS ad_snapshots (           -- LOCAL ONLY; never federated
  app_id TEXT, platform TEXT, creative_id TEXT, ad_snapshot_url TEXT,
  first_seen DATE, last_seen DATE, still_active INTEGER,
  PRIMARY KEY (app_id, platform, creative_id)
);

CREATE TABLE IF NOT EXISTS creator_mentions (       -- LOCAL ONLY; never federated
  app_id TEXT, source TEXT, video_id TEXT, channel TEXT, url TEXT,
  mention_confidence REAL, captured_on DATE,
  PRIMARY KEY (app_id, source, video_id)
);

CREATE TABLE IF NOT EXISTS reviews (
  app_id TEXT, source TEXT, review_id TEXT, rating INTEGER, captured_on DATE,
  PRIMARY KEY (app_id, source, review_id)
);
"""

# Tables that §8 declares (used by bootstrap verification + tests).
EXPECTED_TABLES: tuple[str, ...] = (
    "apps",
    "rank_history",
    "install_buckets",
    "flow_anchors",
    "calibration",
    "estimates",
    "ad_snapshots",
    "creator_mentions",
    "reviews",
)


def _mode(values: list[object]) -> object | None:
    """Most-common non-null value (ties broken by first occurrence)."""
    counts: dict[object, int] = {}
    for v in values:
        if v is None:
            continue
        counts[v] = counts.get(v, 0) + 1
    if not counts:
        return None
    return max(counts, key=lambda k: counts[k])


class Database:
    """Thin wrapper over a local SQLite database.

    The connection is opened lazily and reused. ``bootstrap()`` is idempotent.
    """

    def __init__(self, path: str | Path = "appscope.db") -> None:
        self.path = str(path)
        self._conn: sqlite3.Connection | None = None

    # -- connection management ------------------------------------------------

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            # Ensure the parent directory exists for nested paths.
            if self.path not in (":memory:", "") and "/" in self.path.replace("\\", "/"):
                Path(self.path).parent.mkdir(parents=True, exist_ok=True)
            # check_same_thread=False: FastAPI serves sync endpoints from a
            # threadpool, so the connection is reused across worker threads.
            # Access stays effectively serialized for this single-user tool.
            self._conn = sqlite3.connect(self.path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA foreign_keys = ON")
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Commit on success, roll back on error."""
        conn = self.conn
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    # -- schema ---------------------------------------------------------------

    def bootstrap(self) -> None:
        """Create all §8 tables (idempotent)."""
        with self.transaction() as conn:
            conn.executescript(SCHEMA)

    def list_tables(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        return [r["name"] for r in rows]

    # -- writes: apps / ranks / buckets / reviews (Stage 1) -------------------

    def upsert_app(self, app: dict) -> None:
        """Insert or update an app's metadata row.

        ``first_seen`` is preserved on update; ``last_updated`` is refreshed.
        """
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO apps (app_id, platform, name, developer, category,
                                  country, price_usd, is_free, first_seen, last_updated)
                VALUES (:app_id, :platform, :name, :developer, :category,
                        :country, :price_usd, :is_free, :captured_on, :captured_on)
                ON CONFLICT(app_id) DO UPDATE SET
                    platform=excluded.platform,
                    name=COALESCE(excluded.name, apps.name),
                    developer=COALESCE(excluded.developer, apps.developer),
                    category=COALESCE(excluded.category, apps.category),
                    country=COALESCE(excluded.country, apps.country),
                    price_usd=COALESCE(excluded.price_usd, apps.price_usd),
                    is_free=COALESCE(excluded.is_free, apps.is_free),
                    last_updated=excluded.last_updated
                """,
                {
                    "app_id": app["app_id"],
                    "platform": app.get("platform"),
                    "name": app.get("name"),
                    "developer": app.get("developer"),
                    "category": app.get("category"),
                    "country": app.get("country"),
                    "price_usd": app.get("price_usd"),
                    "is_free": app.get("is_free"),
                    "captured_on": app.get("captured_on"),
                },
            )

    def insert_rank(self, row: dict) -> None:
        """Insert one rank_history row (one per app/country/list/category/date)."""
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO rank_history
                    (app_id, country, list_type, category, rank, captured_on)
                VALUES (:app_id, :country, :list_type, :category, :rank, :captured_on)
                """,
                {
                    "app_id": row["app_id"],
                    "country": row.get("country"),
                    "list_type": row.get("list_type"),
                    "category": row.get("category", "all"),
                    "rank": row.get("rank"),
                    "captured_on": row.get("captured_on"),
                },
            )

    def insert_install_bucket(self, row: dict) -> None:
        """Insert one Android install_buckets row (the anchor source, FR3)."""
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO install_buckets
                    (app_id, min_installs, real_installs, captured_on)
                VALUES (:app_id, :min_installs, :real_installs, :captured_on)
                """,
                {
                    "app_id": row["app_id"],
                    "min_installs": row.get("min_installs"),
                    "real_installs": row.get("real_installs"),
                    "captured_on": row.get("captured_on"),
                },
            )

    def insert_reviews(self, rows: list[dict]) -> int:
        """Insert reviews, deduped by (app_id, source, review_id). Returns count inserted."""
        n = 0
        with self.transaction() as conn:
            for r in rows:
                cur = conn.execute(
                    """
                    INSERT OR IGNORE INTO reviews
                        (app_id, source, review_id, rating, captured_on)
                    VALUES (:app_id, :source, :review_id, :rating, :captured_on)
                    """,
                    {
                        "app_id": r["app_id"],
                        "source": r.get("source"),
                        "review_id": r.get("review_id"),
                        "rating": r.get("rating"),
                        "captured_on": r.get("captured_on"),
                    },
                )
                n += cur.rowcount
        return n

    # -- reads (used by estimator, API, MCP) ----------------------------------

    def get_app(self, app_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM apps WHERE app_id = ?", (app_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_install_buckets(self, app_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM install_buckets WHERE app_id = ? ORDER BY captured_on",
            (app_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_ranks(
        self, app_id: str, country: str = "us", days: int = 30
    ) -> list[dict]:
        rows = self.conn.execute(
            """
            SELECT * FROM rank_history
            WHERE app_id = ? AND country = ?
              AND captured_on >= date('now', ?)
            ORDER BY captured_on
            """,
            (app_id, country, f"-{int(days)} days"),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_latest_rank(
        self, app_id: str, country: str = "us"
    ) -> dict | None:
        row = self.conn.execute(
            """
            SELECT * FROM rank_history
            WHERE app_id = ? AND country = ?
            ORDER BY captured_on DESC LIMIT 1
            """,
            (app_id, country),
        ).fetchone()
        return dict(row) if row else None

    def get_reviews(self, app_id: str, days: int = 30) -> list[dict]:
        rows = self.conn.execute(
            """
            SELECT * FROM reviews
            WHERE app_id = ? AND captured_on >= date('now', ?)
            ORDER BY captured_on DESC
            """,
            (app_id, f"-{int(days)} days"),
        ).fetchall()
        return [dict(r) for r in rows]

    # -- flow anchors + calibration (Stage 2 / Stage 4) -----------------------

    _ANCHOR_COLS = (
        "platform",
        "category",
        "country",
        "list_type",
        "rank",
        "observed_downloads",
        "window_days",
        "captured_on",
    )

    def insert_flow_anchors(self, rows: list[dict], source: str = "local") -> int:
        """Insert flow_anchors rows tagged with ``source`` ('local'|'community').

        Deduped by the full PK; returns the number of newly inserted rows.
        """
        n = 0
        with self.transaction() as conn:
            for r in rows:
                cur = conn.execute(
                    """
                    INSERT OR IGNORE INTO flow_anchors
                        (platform, category, country, list_type, rank,
                         observed_downloads, window_days, captured_on, source)
                    VALUES (:platform, :category, :country, :list_type, :rank,
                            :observed_downloads, :window_days, :captured_on, :source)
                    """,
                    {
                        "platform": r.get("platform"),
                        "category": r.get("category", "all"),
                        "country": r.get("country", "us"),
                        "list_type": r.get("list_type", "top-free"),
                        "rank": r.get("rank"),
                        "observed_downloads": r.get("observed_downloads"),
                        "window_days": r.get("window_days"),
                        "captured_on": r.get("captured_on"),
                        "source": source,
                    },
                )
                n += cur.rowcount
        return n

    def get_segment_anchors(
        self, platform: str, list_type: str, category: str, country: str
    ) -> list[dict]:
        rows = self.conn.execute(
            """
            SELECT rank, observed_downloads, window_days, source FROM flow_anchors
            WHERE platform = ? AND list_type = ? AND category = ? AND country = ?
            """,
            (platform, list_type, category, country),
        ).fetchall()
        return [dict(r) for r in rows]

    def list_anchor_segments(self) -> list[tuple[str, str, str, str]]:
        rows = self.conn.execute(
            """
            SELECT DISTINCT platform, list_type, category, country
            FROM flow_anchors
            """
        ).fetchall()
        return [(r["platform"], r["list_type"], r["category"], r["country"]) for r in rows]

    def get_calibration(
        self, platform: str, list_type: str, category: str, country: str
    ) -> dict | None:
        row = self.conn.execute(
            """
            SELECT * FROM calibration
            WHERE platform = ? AND list_type = ? AND category = ? AND country = ?
            """,
            (platform, list_type, category, country),
        ).fetchone()
        return dict(row) if row else None

    def upsert_calibration(self, row: dict) -> None:
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO calibration
                    (platform, list_type, category, country, shape_a, scale_b, n_anchors, updated_on)
                VALUES (:platform, :list_type, :category, :country, :shape_a, :scale_b, :n_anchors, :updated_on)
                """,
                row,
            )

    def seed_flow_anchors_from_buckets(self) -> int:
        """Derive local Android flow anchors from install-bucket deltas + ranks (FR8).

        For each Android app with >=2 install-bucket captures, derive one anchor
        using the app's observed ranks over the window, tagged with the app's
        category and the modal (country, list_type) from its rank rows.
        """
        from .estimate.calibrate import derive_flow_anchor

        inserted = 0
        android_ids = [
            r["app_id"]
            for r in self.conn.execute(
                "SELECT DISTINCT app_id FROM install_buckets"
            ).fetchall()
        ]
        for app_id in android_ids:
            buckets = self.get_install_buckets(app_id)
            rank_rows = self.conn.execute(
                "SELECT rank, country, list_type, category, captured_on "
                "FROM rank_history WHERE app_id = ? ORDER BY captured_on",
                (app_id,),
            ).fetchall()
            rank_rows = [dict(r) for r in rank_rows]
            anchor = derive_flow_anchor(buckets, rank_rows)
            if not anchor:
                continue
            app = self.get_app(app_id) or {}
            # Modal segment dims from the rank rows (fallbacks are conservative).
            country = _mode([r.get("country") for r in rank_rows]) or app.get("country") or "us"
            list_type = _mode([r.get("list_type") for r in rank_rows]) or "top-free"
            category = app.get("category") or _mode([r.get("category") for r in rank_rows]) or "all"
            captured_on = buckets[-1]["captured_on"]
            anchor.update(
                {
                    "category": category,
                    "country": country,
                    "list_type": list_type,
                    "captured_on": captured_on,
                }
            )
            inserted += self.insert_flow_anchors([anchor], source="local")
        return inserted

    def load_example_anchors(
        self, path: str | Path = "data/anchors.example.json"
    ) -> int:
        """Load SYNTHETIC example anchors for tests/demos only. Idempotent.

        WARNING: ``data/anchors.example.json`` is fabricated demo data, not real
        observations. Do NOT call this on a production database you contribute
        from — it would taint your local calibration and, if shared, violate P8
        ('pool observations, never fabricated numbers'). Real anchors come from
        ``seed_flow_anchors_from_buckets`` (your own captures) or
        ``refresh_dataset`` (the community dataset). The loader refuses files not
        explicitly marked ``"_synthetic": true``.
        """
        import json

        p = Path(path)
        if not p.exists():
            return 0
        data = json.loads(p.read_text(encoding="utf-8"))
        if not data.get("_synthetic"):
            raise ValueError(
                f"{p} is not marked '_synthetic': true; refusing to load as example data"
            )
        anchors = data.get("anchors", [])
        return self.insert_flow_anchors(anchors, source="community")

    def recalibrate_all_segments(self) -> int:
        """Refit ``scale_b`` per (platform, list_type, category, country) from pooled
        anchors (local + community). Returns the number of segments calibrated."""
        from .estimate.calibrate import calibrate_scale, shape_a

        today = self.conn.execute("SELECT date('now') d").fetchone()["d"]
        n_segments = 0
        for platform, list_type, category, country in self.list_anchor_segments():
            anchors = self.get_segment_anchors(platform, list_type, category, country)
            a = shape_a(platform, list_type)
            scale_b, n = calibrate_scale(anchors, a)
            self.upsert_calibration(
                {
                    "platform": platform,
                    "list_type": list_type,
                    "category": category,
                    "country": country,
                    "shape_a": a,
                    "scale_b": scale_b,
                    "n_anchors": n,
                    "updated_on": today,
                }
            )
            n_segments += 1
        return n_segments

    # -- federation reads/writes (Stage 4) ------------------------------------

    def fetch_shareable_anchors(self) -> list[dict]:
        """Local flow anchors as shareable public-fact rows (no app identity).

        Returns rows limited to the §8 shared-anchor field space — never any
        ad/creator/identity column. ``contribute.py`` strips again as defense in
        depth.
        """
        rows = self.conn.execute(
            """
            SELECT platform, category, country, list_type, rank,
                   observed_downloads, window_days, captured_on
            FROM flow_anchors WHERE source = 'local'
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def dedup_against_local(self, incoming: list[dict]) -> list[dict]:
        """Return only the incoming community rows not already present locally."""
        existing = {
            (r["platform"], r["category"], r["country"], r["list_type"], r["rank"], r["captured_on"])
            for r in (
                dict(x)
                for x in self.conn.execute(
                    "SELECT platform, category, country, list_type, rank, captured_on FROM flow_anchors"
                ).fetchall()
            )
        }
        out: list[dict] = []
        for r in incoming:
            key = (
                r.get("platform"),
                r.get("category", "all"),
                r.get("country", "us"),
                r.get("list_type", "top-free"),
                r.get("rank"),
                r.get("captured_on"),
            )
            if key not in existing:
                out.append(r)
        return out

    def calibration_coverage(self, min_anchors: int = 5) -> dict:
        """KPI K6: share of segments with >= ``min_anchors`` pooled anchors."""
        rows = [dict(r) for r in self.conn.execute("SELECT n_anchors FROM calibration").fetchall()]
        total = len(rows)
        covered = sum(1 for r in rows if (r["n_anchors"] or 0) >= min_anchors)
        return {
            "segments": total,
            "covered": covered,
            "coverage": round(covered / total, 3) if total else 0.0,
            "min_anchors": min_anchors,
        }

    # -- ads + creators (Stage 3; LOCAL ONLY, never federated) ----------------

    def upsert_ad_snapshots(
        self, app_id: str, platform: str, snapshots: list[dict]
    ) -> int:
        """Daily ad-snapshot upsert building first_seen/last_seen/still_active.

        New creatives are inserted; previously-seen creatives have ``last_seen``
        and ``still_active`` refreshed. Creatives for this (app, platform) not in
        the current batch are marked ``still_active=0``. Returns rows touched.
        """
        seen_ids = {s.get("creative_id") for s in snapshots if s.get("creative_id")}
        touched = 0
        with self.transaction() as conn:
            for s in snapshots:
                cid = s.get("creative_id")
                if not cid:
                    continue
                existing = conn.execute(
                    "SELECT first_seen FROM ad_snapshots WHERE app_id=? AND platform=? AND creative_id=?",
                    (app_id, platform, cid),
                ).fetchone()
                first_seen = existing["first_seen"] if existing else s.get("first_seen")
                conn.execute(
                    """
                    INSERT INTO ad_snapshots
                        (app_id, platform, creative_id, ad_snapshot_url,
                         first_seen, last_seen, still_active)
                    VALUES (:app_id, :platform, :creative_id, :ad_snapshot_url,
                            :first_seen, :last_seen, :still_active)
                    ON CONFLICT(app_id, platform, creative_id) DO UPDATE SET
                        ad_snapshot_url=excluded.ad_snapshot_url,
                        last_seen=excluded.last_seen,
                        still_active=excluded.still_active
                    """,
                    {
                        "app_id": app_id,
                        "platform": platform,
                        "creative_id": cid,
                        "ad_snapshot_url": s.get("ad_snapshot_url"),
                        "first_seen": first_seen,
                        "last_seen": s.get("last_seen"),
                        "still_active": s.get("still_active", 1),
                    },
                )
                touched += 1
            # Mark creatives no longer present as inactive.
            if seen_ids:
                placeholders = ",".join("?" for _ in seen_ids)
                conn.execute(
                    f"""
                    UPDATE ad_snapshots SET still_active=0
                    WHERE app_id=? AND platform=? AND creative_id NOT IN ({placeholders})
                    """,
                    (app_id, platform, *seen_ids),
                )
        return touched

    def get_ad_snapshots(self, app_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM ad_snapshots WHERE app_id = ?", (app_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def insert_creator_mentions(self, rows: list[dict]) -> int:
        """Insert creator mentions, deduped by (app_id, source, video_id)."""
        n = 0
        with self.transaction() as conn:
            for r in rows:
                cur = conn.execute(
                    """
                    INSERT OR IGNORE INTO creator_mentions
                        (app_id, source, video_id, channel, url, mention_confidence, captured_on)
                    VALUES (:app_id, :source, :video_id, :channel, :url, :mention_confidence, :captured_on)
                    """,
                    {
                        "app_id": r["app_id"],
                        "source": r.get("source"),
                        "video_id": r.get("video_id"),
                        "channel": r.get("channel"),
                        "url": r.get("url"),
                        "mention_confidence": r.get("mention_confidence"),
                        "captured_on": r.get("captured_on"),
                    },
                )
                n += cur.rowcount
        return n

    def get_creator_mentions(
        self, app_id: str, min_confidence: float = 0.6
    ) -> list[dict]:
        rows = self.conn.execute(
            """
            SELECT * FROM creator_mentions
            WHERE app_id = ? AND mention_confidence >= ?
            ORDER BY mention_confidence DESC
            """,
            (app_id, min_confidence),
        ).fetchall()
        return [dict(r) for r in rows]

    # -- estimate persistence -------------------------------------------------

    def upsert_estimate(self, row: dict) -> None:
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO estimates
                    (app_id, country, captured_on, downloads_point, downloads_low,
                     downloads_high, revenue_point, confidence, method, flags)
                VALUES (:app_id, :country, :captured_on, :downloads_point, :downloads_low,
                        :downloads_high, :revenue_point, :confidence, :method, :flags)
                """,
                row,
            )


def bootstrap(path: str | Path = "appscope.db") -> Database:
    """Convenience: open a database at ``path`` and create the schema."""
    db = Database(path)
    db.bootstrap()
    return db
