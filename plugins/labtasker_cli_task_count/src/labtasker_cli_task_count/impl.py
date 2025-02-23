from labtasker.client.core.api import ls_tasks


def get_counts(limit=100):
    status = ["pending", "running", "success", "failed", "cancelled"]
    results = {}
    for s in status:
        cnt = len(ls_tasks(extra_filter={"status": s}, limit=limit).content)
        if cnt >= limit:
            results[s] = f">= {limit}"
        else:
            results[s] = cnt
    return results
