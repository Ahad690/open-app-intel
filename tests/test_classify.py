"""Stage 3 tests — mention classifier precision gate (§14, K5 >= 0.8)."""
from __future__ import annotations

from appscope.creators.classify import app_mention_score, classify_items

APP_NAME = "MyApp"
PACKAGE = "com.myco.myapp"
HASHTAGS = ("#myapp",)
THRESHOLD = 0.6

# Hand-labeled sample: (text, is_truly_about_app).
LABELED_SAMPLE: list[tuple[str, bool]] = [
    # --- true positives (about the app, strong signals) ---
    ("Check out MyApp! play.google.com/store/apps/details?id=com.myco.myapp", True),
    ("MyApp honest review #myapp it changed my workflow", True),
    ("Download MyApp from apps.apple.com/us/app/myapp/id123", True),
    ("com.myco.myapp tutorial — get it on play.google.com/store/apps/details", True),
    ("MyApp is great, grab it here play.google.com/store/apps/details?id=com.myco.myapp", True),
    ("Honest MyApp walkthrough #myapp link apps.apple.com/app/id999", True),
    # --- true negatives (not about the app, weak/no signals) ---
    ("Today I went hiking in the mountains, beautiful weather", False),
    ("The best productivity apps of 2025, a roundup", False),
    ("I use MyApp sometimes but mostly other tools", False),  # name only -> below threshold
    ("Check play.google.com/store/apps for cool stuff", False),  # link only -> below threshold
    ("My morning routine and coffee setup tour", False),
    # --- a realistic false-positive trap (name substring + link to a DIFFERENT app) ---
    ("MyApp is a common phrase, but watch this other game: "
     "play.google.com/store/apps/details?id=com.other.game", False),
]


def test_score_signals():
    assert app_mention_score("I love MyApp", APP_NAME) == 0.5
    assert app_mention_score("see apps.apple.com/app/id1", APP_NAME) == 0.4
    assert app_mention_score("MyApp apps.apple.com/app/id1", APP_NAME) == 0.9
    assert app_mention_score("nothing relevant here", APP_NAME) == 0.0
    # Isolate the package signal with a name that is NOT a substring of the id.
    assert app_mention_score("com.acme.widget", "Zephyr", "com.acme.widget") == 0.3
    assert app_mention_score("MyApp #myapp", APP_NAME, brand_hashtags=HASHTAGS) == 0.7


def test_score_capped_at_one():
    text = "MyApp com.myco.myapp #myapp play.google.com/store/apps/details"
    assert app_mention_score(text, APP_NAME, PACKAGE, HASHTAGS) == 1.0


def test_classifier_precision_at_least_080():
    items = [{"text": t, "label": lbl} for t, lbl in LABELED_SAMPLE]
    flagged = classify_items(items, APP_NAME, PACKAGE, HASHTAGS, min_confidence=THRESHOLD)
    assert flagged, "expected the classifier to flag at least some items"
    true_pos = sum(1 for it in flagged if it["label"] is True)
    precision = true_pos / len(flagged)
    assert precision >= 0.8, f"precision {precision:.3f} below K5 gate (flagged={len(flagged)})"


def test_classify_items_adds_confidence_and_threshold():
    items = [{"text": "I use MyApp sometimes"}]  # 0.5 < 0.6
    assert classify_items(items, APP_NAME, min_confidence=0.6) == []
    items = [{"text": "MyApp #myapp", "video_id": "x"}]  # 0.7 >= 0.6
    out = classify_items(items, APP_NAME, brand_hashtags=HASHTAGS, min_confidence=0.6)
    assert out and out[0]["mention_confidence"] == 0.7
