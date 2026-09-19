"""Q3 — generate 8 deterministic shards of user-signup records.

Same seeded-synthetic pattern as the spam dataset: seed is fixed, so the number
of deliberately invalid rows per shard is KNOWN ahead of time and the Job's
reported counts can be checked against ground truth.

Each shard gets a different corruption rate (shard i corrupts ~ (i+1)*3 % of
rows) so the per-shard results are visibly distinct in the collected logs.

Invalid rows are of two kinds:
  - malformed email   (missing @, missing TLD, leading dot, spaces, empty)
  - missing required field (blank user_id / signup_date / country)
"""
import csv
import os
import random

SHARDS = 8
ROWS_PER_SHARD = 250
SEED = 42

FIRST = ["asha", "ravi", "meera", "arjun", "priya", "kiran", "nisha", "vikram"]
LAST = ["nair", "iyer", "reddy", "khan", "bose", "menon", "shah", "rao"]
DOMAINS = ["example.com", "mailbox.org", "testmail.in", "corp.co"]
COUNTRIES = ["IN", "US", "DE", "SG", "AU"]
DATES = [f"2026-0{m}-{d:02d}" for m in range(1, 7) for d in (3, 11, 19, 27)]

BAD_EMAIL_FORMS = [
    "{u}example.com",        # missing @
    "{u}@example",           # missing TLD
    ".{u}@example.com",      # leading dot in local part
    "{u} name@example.com",  # space in local part
    "@example.com",          # empty local part
    "",                      # empty entirely
]

HEADER = ["user_id", "name", "email", "signup_date", "country"]
REQUIRED = ["user_id", "signup_date", "country"]


def main(out_dir: str = "shards") -> None:
    rng = random.Random(SEED)
    os.makedirs(out_dir, exist_ok=True)
    manifest = []

    for shard in range(SHARDS):
        corrupt_rate = (shard + 1) * 0.03
        invalid = 0
        path = os.path.join(out_dir, f"shard_{shard}.csv")
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(HEADER)
            for i in range(ROWS_PER_SHARD):
                uid = f"u{shard:02d}{i:04d}"
                first, last = rng.choice(FIRST), rng.choice(LAST)
                name = f"{first.capitalize()} {last.capitalize()}"
                email = f"{first}.{last}{i}@{rng.choice(DOMAINS)}"
                date = rng.choice(DATES)
                country = rng.choice(COUNTRIES)

                if rng.random() < corrupt_rate:
                    invalid += 1
                    if rng.random() < 0.6:
                        email = rng.choice(BAD_EMAIL_FORMS).format(u=f"{first}.{last}{i}")
                    else:
                        field = rng.choice(REQUIRED)
                        if field == "user_id":
                            uid = ""
                        elif field == "signup_date":
                            date = ""
                        else:
                            country = ""
                w.writerow([uid, name, email, date, country])

        manifest.append((shard, ROWS_PER_SHARD, invalid))
        print(f"{path}: {ROWS_PER_SHARD} rows, {invalid} deliberately invalid "
              f"({corrupt_rate:.0%} target)")

    with open(os.path.join(out_dir, "GROUND_TRUTH.txt"), "w", encoding="utf-8") as fh:
        fh.write("shard,total_rows,invalid_rows\n")
        for shard, total, invalid in manifest:
            fh.write(f"{shard},{total},{invalid}\n")
    print("\nwrote shards/GROUND_TRUTH.txt (used to verify the Job's reported counts)")


if __name__ == "__main__":
    main()
