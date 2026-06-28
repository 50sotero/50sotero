import timeit
import datetime
from dataclasses import dataclass

@dataclass
class CommitStat:
    date: datetime.datetime

commit_stats = [CommitStat(datetime.datetime(2023, 1, 1) + datetime.timedelta(days=i, hours=j)) for i in range(100) for j in range(24)]

def orig():
    return len({commit.date.date().isoformat() for commit in commit_stats})

def opt():
    return len({commit.date.date() for commit in commit_stats})

orig_time = timeit.timeit(orig, number=1000)
opt_time = timeit.timeit(opt, number=1000)

print(f"Original: {orig_time:.4f}")
print(f"Optimized: {opt_time:.4f}")
print(f"Improvement: {(orig_time - opt_time) / orig_time * 100:.2f}%")
