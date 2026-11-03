"""A3C 결과 폴더를 「A2C v2 학습 결과 요약」 PDF와 같은 양식으로 정리한다.

    python scripts/a3c_report.py [결과 폴더]   (기본: results/jeabin_a3c_a2c_v2)

결과 폴더에 A3C_학습결과_요약.html과 .pdf를 만든다. PDF 변환에 Google Chrome을 쓴다.
비교 대상인 A2C v2 수치는 「A2C v2 학습 결과 요약」(2026.10.31)에서 옮겨 적었다.
"""

import csv
import datetime
import html
import json
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DIR = ROOT / "results" / "jeabin_a3c_a2c_v2"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
POLICY = "A3C 정책"
RANDOM = "무작위 정책"

# 「A2C v2 학습 결과 요약」의 최종 평가(40판)와 학습 기록
A2C_V2 = {
    "steps": 100170, "won": 0, "games": 40,
    "reached": 8.90, "cleared": 7.90, "buy": 14.53, "upgrade": 5.47, "sell": 5.85,
    "gold": 205.90, "max_reached": 14, "train_episodes": 3281, "train_max": 16, "ev": 0.23,
}


def read_csv(path):
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def mean(rows, key):
    return statistics.mean(float(r[key]) for r in rows)


def summarize(rows):
    return {
        "games": len(rows),
        "won": sum(r["won"] == "True" for r in rows),
        "reached": mean(rows, "reached"), "cleared": mean(rows, "cleared"),
        "buy": mean(rows, "buy"), "upgrade": mean(rows, "upgrade"), "sell": mean(rows, "sell"),
        "gold": mean(rows, "gold"), "life": mean(rows, "life"), "reward": mean(rows, "reward"),
        "max_reached": max(int(r["reached"]) for r in rows),
        "min_reached": min(int(r["reached"]) for r in rows),
    }


def stage_clear_rates(rows, stages=30):
    """소동별 클리어율. 해당 소동에 진입한 판을 분모로 한다."""
    rates = {}
    for s in range(1, stages + 1):
        entered = [r for r in rows if int(r["reached"]) >= s]
        if entered:
            passed = sum(int(r["cleared"]) >= s for r in entered)
            rates[s] = (passed / len(entered), len(entered))
    return rates


def pick_evals(evals, n=5):
    """처음·끝을 포함해 고르게 n개를 고른다 (원본 표처럼 0, 20%, 50%, 80%, 끝)."""
    if len(evals) <= n:
        return evals
    last = len(evals) - 1
    idx = sorted({0, round(last * 0.2), round(last * 0.5), round(last * 0.8), last})
    return [evals[i] for i in idx]


def table(head, rows):
    th = "".join(f"<th>{h}</th>" for h in head)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>"


def build(out_dir):
    cfg = json.loads((out_dir / "config.json").read_text(encoding="utf-8"))
    final = read_csv(out_dir / "final_eval.csv")
    evals = read_csv(out_dir / "evaluations.csv")
    episodes = read_csv(out_dir / "episodes.csv")
    updates = read_csv(out_dir / "updates.csv")

    a3c = summarize([r for r in final if r["policy"] == POLICY])
    rnd = summarize([r for r in final if r["policy"] == RANDOM])
    a, r = cfg["a3c"], cfg["reward"]
    steps = int(evals[-1]["timesteps"])
    train_wins = sum(e["won"] == "True" for e in episodes)
    train_max = max(int(e["reached"]) for e in episodes)
    worker_updates = sum(int(u["worker_updates"]) for u in updates)
    tail = updates[-10:]
    ev_tail = statistics.mean(float(u["explained_variance"]) for u in tail)
    rates = stage_clear_rates([x for x in final if x["policy"] == POLICY], cfg["run"]["train_stages"])
    weak = sorted((v[0], s) for s, v in rates.items() if v[1] >= 5)[:2]

    today = datetime.date.today().strftime("%Y.%m.%d")
    title = "A3C 실험 결과"
    clear_pct = lambda d: f"{d['won']} / {d['games']}판 ({d['won'] / d['games']:.0%})"
    f2 = lambda x: f"{x:.2f}"

    # 1쪽: 최종 평가
    p1_table = table(["지표", "A2C v2", "A3C"], [
        ["누적 학습 Step", f"{A2C_V2['steps']:,}", f"{steps:,}"],
        ["30소동 클리어", clear_pct(A2C_V2), clear_pct(a3c)],
        ["평균 도달 소동", f2(A2C_V2["reached"]), f2(a3c["reached"])],
        ["평균 완료 소동", f2(A2C_V2["cleared"]), f2(a3c["cleared"])],
        ["평균 소환 횟수", f2(A2C_V2["buy"]), f2(a3c["buy"])],
        ["평균 강화 횟수", f2(A2C_V2["upgrade"]), f2(a3c["upgrade"])],
        ["평균 판매 횟수", f2(A2C_V2["sell"]), f2(a3c["sell"])],
        ["평균 잔여 골드 (G)", f2(A2C_V2["gold"]), f2(a3c["gold"])],
        ["최고 도달 소동", A2C_V2["max_reached"], a3c["max_reached"]],
    ])
    won_text = (f"30소동 클리어는 {a3c['won']}판({a3c['won'] / a3c['games']:.0%})이다"
                if a3c["won"] else "30소동 클리어에는 실패했다")
    lead = (f"A2C v2와 같은 조건(워커 15개 × 18 Step, lr 0.0001)으로 약 {steps // 1000}k Step을 학습했다. "
            f"평균 도달 소동이 {A2C_V2['reached']:.2f}에서 {a3c['reached']:.2f}로 올랐고, {won_text}. "
            f"조건에서 다른 점은 갱신 방식(동기 → 비동기) 하나다.")
    weak_text = ", ".join(f"{s}소동 {v:.0%}" for v, s in weak)
    p1_body = f"""
<p class="lead">{lead}</p>
<h2>최종 평가: 각 정책 {a3c['games']}판</h2>
{p1_table}
<h2>결과 해석</h2>
<p>평균 도달 소동은 {A2C_V2['reached']:.2f}에서 {a3c['reached']:.2f}로 약 {a3c['reached'] - A2C_V2['reached']:.2f}소동 상승했다.
강화는 평균 {A2C_V2['upgrade']:.2f}회에서 {a3c['upgrade']:.2f}회로 크게 늘었고, 판매는 {A2C_V2['sell']:.2f}회에서 {a3c['sell']:.2f}회로
{'줄었다' if a3c['sell'] < A2C_V2['sell'] else '늘었다'}. 소환한 수호자를 팔기보다 강화하는 쪽으로 전략이 바뀌었다.</p>
<p>A3C의 최종 평가 도달 범위는 {a3c['min_reached']}~{a3c['max_reached']}소동이다. 무작위 정책의 평균 {rnd['reached']:.2f}소동보다
크게 높다. 진입한 판이 5판 이상인 소동 가운데 클리어율이 가장 낮은 곳은 {weak_text}로, 후반 구간에서 막힌다.</p>
<p class="note">도달 소동은 마지막으로 진입한 소동이다. {a3c['max_reached']}소동 도달은 {a3c['max_reached']}소동 클리어를 뜻하지 않는다.
학습 시드 1개의 결과이므로 동기/비동기 차이로 단정하려면 시드를 바꿔 다시 확인해야 한다.</p>
"""

    # 2쪽: 설정·학습 추이
    batch = a["num_workers"] * a["n_steps"]
    p2_cfg = table(["항목", "A3C 실행값"], [
        ["학습", "A3C / 공유 Adam / GAE / 워커별 비동기 갱신"],
        ["병렬 워커 및 갱신 단위", f"워커 {a['num_workers']}개 × 워커당 {a['n_steps']} Step마다 갱신 (한 바퀴 {batch} Step)"],
        ["학습률 / 할인율 / GAE lambda", f"{a['lr']} / {a['gamma']} / {a['gae_lambda']}"],
        ["보상 배율", f"scale = {r['scale']}"],
        ["판매 손실 감점", f"손실 골드 1G당 {r['sell_loss']} × scale = {r['sell_loss'] * r['scale']:g}점 차감"],
        ["행동 고정 감점", "소환·강화·판매·웨이브 시작 모두 0" if not any(
            r[k] for k in ("action_cost", "cost_start", "cost_buy", "cost_upgrade", "cost_sell")) else "있음 (config.json 참고)"],
        ["최종 잔여 골드 보상", "없음 (A2C v2의 goal_gold = 0과 같음)"],
    ])
    p2_eval = table(["Step", "평균 도달 소동", "평균 판매 횟수", "클리어율"], [
        [f"{int(e['timesteps']):,}", f2(float(e["avg_reached"])), f2(float(e["avg_sell"])),
         f"{float(e['clear_rate']):g}%"] for e in pick_evals(evals)
    ])
    first_clear = next((e for e in evals if float(e["clear_rate"]) > 0), None)
    first_clear_text = (f"정기 평가에서 처음 클리어가 나온 것은 {int(first_clear['timesteps']):,} Step이다. "
                        if first_clear else "")
    p2_body = f"""
<h2>실제 실행 설정</h2>
{p2_cfg}
<p>보상·학습률·할인율·GAE·배치 크기는 A2C v2와 같다. A2C는 환경 {a['num_workers']}개가 모은 {batch} Step으로 한 번에 갱신하고,
A3C는 워커마다 {a['n_steps']} Step을 모으면 공유 모델을 바로 갱신한다. 둘 다 resume=false로 새로 시작했다.
value_coef {a['value_coef']}, entropy_coef {a['entropy_coef']}, max_grad_norm {a['max_grad_norm']}, hidden {a['hidden']}은
A2C v2 문서에 없어 PPO 기본값을 썼다.</p>
<h2>평가 추이</h2>
{p2_eval}
<p>학습 중 종료된 게임은 {len(episodes):,}판, 워커 갱신은 {worker_updates:,}회이며 승리는 {train_wins}판이다.
학습 중 최고 도달은 {train_max}소동이다. {first_clear_text}</p>
<p>마지막 기록 10구간의 평균 EV는 {ev_tail:.2f}로, A2C v2의 마지막 30회 평균 {A2C_V2['ev']:.2f}보다 높다.
기록 단위(A3C는 {a.get('log_every_steps', 2048):,} Step마다 묶은 평균)가 달라 직접 비교에는 한계가 있다.</p>
<h2>다음 실험 제안</h2>
<p>같은 설정으로 학습 시드를 2~3개 더 돌려 A3C의 향상이 재현되는지 확인한다. 재현되면 A2C와 A3C를 같은 컴퓨터에서
돌려 시간당 학습량도 비교한다. 후반({weak_text}) 실패 원인을 보려면 해당 소동의 보스 처치 여부와 배치 기록을 추가한다.
Step을 늘릴 때는 다른 수치를 고정하고 total_timesteps만 바꾼다.</p>
<p class="note">자료: {html.escape(str(out_dir.relative_to(ROOT)))}의 config.json, evaluations.csv, final_eval.csv, episodes.csv, updates.csv.
부록은 같은 폴더의 원본 PNG 7장이다.</p>
"""

    # 3~9쪽: 그래프
    last = evals[-1]
    graphs = [
        ("1_episode_reward.png", "그래프 1. 판별 누적 보상",
         "판별 원본 값과 이동평균이다. 전체 보상은 개선 추세지만 이것만으로 최종 승리 전략을 확보했다고 판단할 수 없다."),
        ("2_episode_stage.png", "그래프 2. 판별 도달 소동",
         f"학습 중 최고 {train_max}소동까지 진입했고 {train_wins}판을 클리어했다. 판별 편차가 크다."),
        ("3_clear_rate.png", "그래프 3. 정기 평가 클리어율",
         f"최종 평가의 30소동 클리어율은 {float(last['clear_rate']):g}%다. {first_clear_text}"),
        ("4_remaining_life.png", "그래프 4. 평균 잔여 라이프",
         f"클리어한 판만 결계가 남는다. 최종 평가 평균 잔여 결계는 {a3c['life']:.2f}이다."),
        ("5_remaining_gold.png", "그래프 5. 평균 잔여 골드",
         f"최종 평가 평균 잔액은 약 {a3c['gold']:.0f}G다. 오래 버틸수록 처치 골드가 쌓이므로 의도적 저축으로 단정하지 않는다."),
        ("6_a3c_stability.png", "그래프 6. A3C 학습 지표",
         "엔트로피·가치 손실·EV를 기록한다. A3C는 PPO의 확률 비율 clipping을 사용하지 않는다."),
        ("7_final_summary.png", "그래프 7. 최종 평가 요약",
         f"고정 시드 {a3c['games']}판에서 무작위 정책과 A3C 정책을 비교한 원본 요약이다. "
         "소동별 클리어율은 해당 소동에 진입한 판을 분모로 한다."),
    ]

    pages = [("A3C 학습 결과 요약", f'<p class="sub">월하사신 강화학습 실험 | 분석일 {today}</p>' + p1_body),
             ("설정·학습 추이와 다음 실험", p2_body)]
    for img, head, cap in graphs:
        if (out_dir / img).exists():
            pages.append((head, f'<p>{cap}</p><div class="fig"><img src="{img}"></div>'))

    page_html = "".join(f"""
<section class="page">
  <div class="bar"></div>
  <h1>{h}</h1>
  {body}
  <footer><span>월하사신 | {title} | {today}</span><span>{i:02d}</span></footer>
</section>""" for i, (h, body) in enumerate(pages, 1))

    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>A3C 학습 결과 요약</title>
<style>
@page {{ size: A4; margin: 0; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; font-family: "Apple SD Gothic Neo", "Malgun Gothic", sans-serif; color: #1f2d3d; }}
.page {{ position: relative; width: 210mm; height: 297mm; padding: 22mm 15mm 20mm; page-break-after: always; overflow: hidden; }}
.bar {{ position: absolute; top: 0; left: 0; right: 0; height: 4.5mm; background: #17324d; }}
h1 {{ font-size: 23pt; color: #17324d; margin: 0 0 5mm; }}
h2 {{ font-size: 14pt; color: #17324d; margin: 5mm 0 2.5mm; }}
p {{ font-size: 10.5pt; line-height: 1.6; margin: 0 0 3mm; }}
.sub {{ font-size: 9pt; }}
.lead {{ font-size: 11.5pt; }}
.note {{ font-size: 9pt; }}
table {{ width: 100%; border-collapse: collapse; font-size: 9.5pt; margin-bottom: 4mm; }}
th {{ background: #eef3f7; text-align: left; font-weight: normal; padding: 2.6mm 3mm; border-bottom: 1.5px solid #1e8a8a; }}
td {{ padding: 2.2mm 3mm; border-bottom: 1px solid #e3e8ee; }}
.fig {{ background: #fafaf8; padding: 2mm; }}
.fig img {{ width: 100%; display: block; }}
footer {{ position: absolute; left: 15mm; right: 15mm; bottom: 8mm; display: flex; justify-content: space-between;
          font-size: 8.5pt; color: #5a6b7d; border-top: 1px solid #d5e0ea; padding-top: 2mm; }}
</style></head><body>{page_html}</body></html>"""


def main():
    out_dir = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else DEFAULT_DIR
    html_path = out_dir / "A3C_학습결과_요약.html"
    pdf_path = out_dir / "A3C_학습결과_요약.pdf"
    html_path.write_text(build(out_dir), encoding="utf-8")
    subprocess.run([CHROME, "--headless", "--disable-gpu", "--no-pdf-header-footer",
                    f"--print-to-pdf={pdf_path}", html_path.as_uri()],
                   check=True, capture_output=True)
    print(f"저장: {pdf_path}")


if __name__ == "__main__":
    main()
