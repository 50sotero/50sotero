import timeit
import datetime
from dataclasses import dataclass

@dataclass
class CommitStat:
    date: datetime.datetime

def build_commit_stats():
    return [
        CommitStat(datetime.datetime(2023, 1, 1) + datetime.timedelta(days=i, hours=j))
        for i in range(100)
        for j in range(24)
    ]

def orig(commit_stats):
    return len({commit.date.date().isoformat() for commit in commit_stats})

def opt(commit_stats):
    return len({commit.date.date() for commit in commit_stats})

def main():
    commit_stats = build_commit_stats()
    orig_time = timeit.timeit(lambda: orig(commit_stats), number=1000)
    opt_time = timeit.timeit(lambda: opt(commit_stats), number=1000)

    print(f"Original: {orig_time:.4f}")
    print(f"Optimized: {opt_time:.4f}")
    print(f"Improvement: {(orig_time - opt_time) / orig_time * 100:.2f}%")

if __name__ == "__main__":
    main()
