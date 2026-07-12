"""EnergyPlus 批跑器 — headless CLI 调用,支持并行与断点续传。

断点续传约定:run_dir 下存在 `_success` 哨兵文件即视为已完成,跳过;
失败格不炸全局,记入返回值的 failed 清单。
"""
from __future__ import annotations

import os
import subprocess
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path


def resolve_eplus_dir(engine: dict, cli_override: str | None = None) -> Path:
    """优先级:CLI > $BS_EPLUS_DIR > config 默认。"""
    p = cli_override or os.environ.get("BS_EPLUS_DIR") or engine["energyplus"]["default_dir"]
    p = Path(p)
    assert (p / "energyplus").exists(), f"energyplus 可执行不存在: {p}"
    return p


def run_one(eplus_dir: Path, idf_path: Path, epw_path: Path, run_dir: Path) -> dict:
    """跑单格;返回 {name, ok, seconds, err_summary}。"""
    import time
    run_dir.mkdir(parents=True, exist_ok=True)
    sentinel = run_dir / "_success"
    if sentinel.exists():
        return {"name": run_dir.name, "ok": True, "seconds": 0.0, "cached": True}
    t0 = time.perf_counter()
    proc = subprocess.run(
        [str(eplus_dir / "energyplus"), "-w", str(epw_path), "-d", str(run_dir),
         "-r", str(idf_path)],
        capture_output=True, text=True)
    dt = time.perf_counter() - t0
    err_file = run_dir / "eplusout.err"
    ok = proc.returncode == 0 and err_file.exists() and \
        "EnergyPlus Completed Successfully" in (err_file.read_text(errors="ignore")[-2000:])
    if ok:
        sentinel.write_text("ok")
    summary = ""
    if not ok:
        tail = err_file.read_text(errors="ignore")[-800:] if err_file.exists() else proc.stderr[-800:]
        summary = tail.replace("\n", " | ")[-400:]
    return {"name": run_dir.name, "ok": ok, "seconds": round(dt, 1),
            "cached": False, "err_summary": summary}


def run_batch(jobs: list[dict], eplus_dir: Path, max_workers: int) -> list[dict]:
    """jobs: [{name, idf, epw, run_dir}];并行跑,单格失败不中断。"""
    results = []
    with ProcessPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(run_one, eplus_dir, j["idf"], j["epw"], j["run_dir"]): j
                for j in jobs}
        for fut in as_completed(futs):
            j = futs[fut]
            try:
                res = fut.result()
            except Exception as e:                      # 进程级失败也进 failed 清单
                res = {"name": j["name"], "ok": False, "seconds": 0.0,
                       "cached": False, "err_summary": f"executor: {e}"}
            results.append(res)
            tag = "cached" if res.get("cached") else ("ok" if res["ok"] else "FAILED")
            print(f"[runner] {res['name']}: {tag} ({res['seconds']}s)", flush=True)
    return sorted(results, key=lambda r: r["name"])
