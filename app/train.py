"""Train TfidfVectorizer + MultinomialNB on spam_dataset.csv and persist with joblib.

Run at IMAGE BUILD TIME (builder stage), never at container start, so the runtime
image never needs pandas or the CSV.
"""
import sys

import joblib
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import classification_report
from sklearn.model_selection import train_test_split
from sklearn.naive_bayes import MultinomialNB
from sklearn.pipeline import Pipeline


def main(csv_path: str = "spam_dataset.csv", out_path: str = "model.joblib") -> None:
    df = pd.read_csv(csv_path)
    X_train, X_test, y_train, y_test = train_test_split(
        df["text"], df["label"], test_size=0.2, random_state=42, stratify=df["label"]
    )

    pipe = Pipeline(
        [
            ("tfidf", TfidfVectorizer(lowercase=True, ngram_range=(1, 2), min_df=1)),
            ("nb", MultinomialNB(alpha=0.1)),
        ]
    )
    pipe.fit(X_train, y_train)

    print(classification_report(y_test, pipe.predict(X_test), digits=4))
    joblib.dump(pipe, out_path)
    print(f"saved pipeline -> {out_path}")


if __name__ == "__main__":
    main(*sys.argv[1:])
