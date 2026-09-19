"""Generate the deterministic synthetic spam/ham dataset (1000 rows).

Exactly the generator given in the assignment brief, wrapped in a main() so it
can be invoked from a Dockerfile RUN step.
"""
import random

import pandas as pd

random.seed(42)

SPAM_TEMPLATES = [
    "WIN a FREE {prize} now! Click here: {url}",
    "Congratulations! You have WON a {prize}. Claim NOW at {url}",
    "URGENT: Your account will be suspended. Verify at {url}",
    "Limited time offer! Get {prize} FREE, click {url} today",
    "You've been selected for a {prize}! Reply YES to claim",
    "Cash prize alert: claim your {prize} before it expires! {url}",
]
HAM_TEMPLATES = [
    "Hey, are we still meeting for {activity} on {day}?",
    "Can you send me the notes from {activity} class?",
    "Don't forget about {activity} this {day}, see you there",
    "Thanks for helping with {activity} yesterday",
    "Running a bit late for {activity}, be there in 10 min",
    "What time does {activity} start on {day}?",
]
PRIZES = ["iPhone", "cash prize", "gift card", "vacation", "laptop"]
URLS = ["bit.ly/xyz123", "tinyurl.com/abc", "win-now.co/claim"]
ACTIVITIES = ["lunch", "the study group", "basketball", "the project meeting"]
DAYS = ["Monday", "Friday", "tomorrow", "the weekend"]


def main(out_path: str = "spam_dataset.csv") -> None:
    rows = []
    for _ in range(1000):
        if random.random() < 0.3:
            t = random.choice(SPAM_TEMPLATES)
            msg = t.format(prize=random.choice(PRIZES), url=random.choice(URLS))
            rows.append((msg, "spam"))
        else:
            t = random.choice(HAM_TEMPLATES)
            msg = t.format(activity=random.choice(ACTIVITIES), day=random.choice(DAYS))
            rows.append((msg, "ham"))
    df = pd.DataFrame(rows, columns=["text", "label"])
    df.to_csv(out_path, index=False)
    print(f"wrote {out_path}: {len(df)} rows, label counts = {df.label.value_counts().to_dict()}")


if __name__ == "__main__":
    main()
