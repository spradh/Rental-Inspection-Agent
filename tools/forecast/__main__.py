"""Demo: python -m project.tools.forecast"""

from .forecast import DB, forecast_net_revenue

if __name__ == "__main__":
    if not DB.exists():
        raise SystemExit("loomco.db not found — run: python -m data.generate")
    print("Net revenue forecast (last 3 actuals + 3 forecast):")
    for p in forecast_net_revenue(3)[-6:]:
        print(f"  {p.month}  {p.value:>12,.0f}  {p.kind}")
