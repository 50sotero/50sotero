import timeit
import time
import zipfile
import io
import json
from pathlib import PurePosixPath
from dataclasses import dataclass
import concurrent.futures

# Mocking the functions and classes needed for count_source_loc_from_archives
from scripts.generate_code_metrics import (
    GitHubClient,
    Repository,
    should_skip,
    language_for,
    MAX_FILE_SIZE,
    count_notebook_data,
    count_text_lines,
    loc_metrics_from_totals,
    LocMetrics
)

@dataclass
class MockRepo:
    name: str
    default_branch: str

class MockClient:
    def __init__(self, latency=0.1):
        self.latency = latency

    def request_bytes(self, path: str) -> bytes:
        time.sleep(self.latency)
        # Create a dummy zip file
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("repo-main/main.py", "print('hello world')\n" * 100)
            zf.writestr("repo-main/utils.py", "def add(a, b): return a + b\n" * 50)
            zf.writestr("repo-main/index.js", "console.log('test');\n" * 200)
        return buf.getvalue()

def count_source_loc_from_archives_sequential(
    client,
    owner: str,
    repositories: list,
) -> LocMetrics:
    totals: dict[str, int] = {}
    files: dict[str, int] = {}
    repos_scanned = 0
    for repo in repositories:
        archive = client.request_bytes(f"/repos/{owner}/{repo.name}/zipball/{repo.default_branch}")
        repos_scanned += 1
        with zipfile.ZipFile(io.BytesIO(archive)) as zip_file:
            for member in zip_file.infolist():
                if member.is_dir():
                    continue
                path = PurePosixPath(member.filename)
                relative_parts = path.parts[1:] if len(path.parts) > 1 else path.parts
                relative = PurePosixPath(*relative_parts)
                if should_skip(relative):
                    continue
                lang = language_for(relative)
                if not lang:
                    continue

                if member.file_size > MAX_FILE_SIZE:
                    continue

                try:
                    with zip_file.open(member) as f:
                        raw = f.read(MAX_FILE_SIZE + 1)
                        if len(raw) > MAX_FILE_SIZE:
                            continue
                except zipfile.BadZipFile:
                    continue

                if lang == "Jupyter Notebook":
                    try:
                        data = json.loads(raw.decode("utf-8", errors="ignore"))
                    except json.JSONDecodeError:
                        continue
                    loc = count_notebook_data(data)
                else:
                    loc = count_text_lines(raw.decode("utf-8", errors="ignore"), lang)
                if loc <= 0:
                    continue
                totals[lang] = totals.get(lang, 0) + loc
                files[lang] = files.get(lang, 0) + 1
    return loc_metrics_from_totals(totals, files, repos_scanned)

def count_source_loc_from_archives_parallel(
    client,
    owner: str,
    repositories: list,
) -> LocMetrics:
    totals: dict[str, int] = {}
    files: dict[str, int] = {}
    repos_scanned = 0

    def _process_repo(repo) -> tuple[dict[str, int], dict[str, int]]:
        archive = client.request_bytes(f"/repos/{owner}/{repo.name}/zipball/{repo.default_branch}")
        repo_totals: dict[str, int] = {}
        repo_files: dict[str, int] = {}
        with zipfile.ZipFile(io.BytesIO(archive)) as zip_file:
            for member in zip_file.infolist():
                if member.is_dir():
                    continue
                path = PurePosixPath(member.filename)
                relative_parts = path.parts[1:] if len(path.parts) > 1 else path.parts
                relative = PurePosixPath(*relative_parts)
                if should_skip(relative):
                    continue
                lang = language_for(relative)
                if not lang:
                    continue

                if member.file_size > MAX_FILE_SIZE:
                    continue

                try:
                    with zip_file.open(member) as f:
                        raw = f.read(MAX_FILE_SIZE + 1)
                        if len(raw) > MAX_FILE_SIZE:
                            continue
                except zipfile.BadZipFile:
                    continue

                if lang == "Jupyter Notebook":
                    try:
                        data = json.loads(raw.decode("utf-8", errors="ignore"))
                    except json.JSONDecodeError:
                        continue
                    loc = count_notebook_data(data)
                else:
                    loc = count_text_lines(raw.decode("utf-8", errors="ignore"), lang)
                if loc <= 0:
                    continue
                repo_totals[lang] = repo_totals.get(lang, 0) + loc
                repo_files[lang] = repo_files.get(lang, 0) + 1
        return repo_totals, repo_files

    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = {executor.submit(_process_repo, repo): repo for repo in repositories}
        for future in concurrent.futures.as_completed(futures):
            repo_totals, repo_files = future.result()
            repos_scanned += 1
            for lang, loc in repo_totals.items():
                totals[lang] = totals.get(lang, 0) + loc
            for lang, count in repo_files.items():
                files[lang] = files.get(lang, 0) + count

    return loc_metrics_from_totals(totals, files, repos_scanned)

def main():
    client = MockClient(latency=0.1) # 100ms latency to simulate network
    repos = [MockRepo(name=f"repo{i}", default_branch="main") for i in range(10)]

    orig_time = timeit.timeit(lambda: count_source_loc_from_archives_sequential(client, "test", repos), number=1)
    opt_time = timeit.timeit(lambda: count_source_loc_from_archives_parallel(client, "test", repos), number=1)

    print(f"Original (Sequential): {orig_time:.4f}s")
    print(f"Optimized (Parallel): {opt_time:.4f}s")
    print(f"Improvement: {(orig_time - opt_time) / orig_time * 100:.2f}%")

if __name__ == "__main__":
    main()
