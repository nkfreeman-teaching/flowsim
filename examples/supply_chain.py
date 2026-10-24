"""A four-stage beer-game supply chain, the bullwhip effect, and factory capacity."""

from pathlib import Path

import polars as pl

from flowsim import Model, compare, moving_average, order_up_to

STAGES = ["Retailer", "Wholesaler", "Distributor", "Factory"]
WEEKS = 104  # two years of weekly reviews
WARMUP = 20  # weeks before measurement, while the empty pipelines fill
REPLICATIONS = 20
BATCH = 25  # cases per brewhouse job


def beer_game(
    forecast_from: str = "orders",
    window: int = 5,
    lead_time: int = 2,
    brew_rate: float | None = None,
    factory_cover: float = 2,
) -> Model:
    """Consumers, a retailer, a wholesaler, a distributor, and a factory.

    Consumer demand averages 100 cases per week with a standard deviation of
    20, and a week that draws below zero sells nothing. Every stage reviews
    weekly, receives shipments two weeks after its supplier sends them, and
    orders up to its forecast lead-time demand plus one standard deviation of
    safety stock. Without brew_rate, the factory's lead time stands in for
    production, since its supplier has unlimited stock.

    With brew_rate (cases per week), the factory instead brews its orders in
    jobs of BATCH cases on one brewhouse, so the brewhouse queue sets its lead
    time. Its target then covers factory_cover weeks of forecast demand.
    """
    model = Model(time_unit="weeks")
    consumers = model.demand(
        name="Consumers",
        per_period=lambda rng: max(0.0, rng.normal(100, 20)),
    )
    stages = [
        model.stock_point(
            name=name,
            initial=100 * lead_time,
            lead_time=lead_time,
            shortage="backorder",
            policy=order_up_to(
                forecast=moving_average(window=window),
                safety_factor=1,
            ),
            forecast_from=forecast_from,
        )
        for name in STAGES[:-1]
    ]
    brews = brew_rate is not None
    factory = model.stock_point(
        name=STAGES[-1],
        initial=100 * lead_time,
        lead_time=None if brews else lead_time,
        batch_size=BATCH if brews else None,
        shortage="backorder",
        policy=order_up_to(
            forecast=moving_average(window=window),
            safety_factor=1,
            cover=factory_cover if brews else None,
        ),
        forecast_from=forecast_from,
    )
    if brews:
        brewhouse = model.station(
            name="Brewhouse",
            capacity=1,
            service_time=1 / brew_rate,
        )
        model.route([factory, brewhouse, factory])
    model.supply(
        [consumers, *stages, factory],
        period=1,
    )
    return model


def bullwhip_study(replications: int = REPLICATIONS, seed: int = 5):
    """Compare forecasting from orders with sharing demand and a longer average."""
    return compare(
        scenarios={
            "Forecast from orders": beer_game(),
            "Share consumer demand": beer_game(forecast_from="end_demand"),
            "Ten-week average": beer_game(window=10),
        },
        duration=WEEKS,
        replications=replications,
        seed=seed,
        warmup=WARMUP,
    )


def capacity_study(replications: int = REPLICATIONS, seed: int = 5):
    """Compare a two-week factory lead time with brewing at three rates.

    Orders follow the same forecasts in every scenario, so a brewhouse rate
    changes how soon the factory's orders arrive but not the orders. The last
    scenario raises the factory's cover from two weeks to three.
    """
    return compare(
        scenarios={
            "Two-week lead time": beer_game(),
            "Brew 120 per week": beer_game(brew_rate=120),
            "Brew 150 per week": beer_game(brew_rate=150),
            "Brew 200 per week": beer_game(brew_rate=200),
            "Brew 150, cover 3": beer_game(
                brew_rate=150,
                factory_cover=3,
            ),
        },
        duration=WEEKS,
        replications=replications,
        seed=seed,
        warmup=WARMUP,
    )


def amplification(comparison) -> pl.DataFrame:
    """Each stage's order variance over consumer demand variance, per scenario.

    The bullwhip ratio divides a stage's order variance by the variance of the
    orders it receives, so it measures one stage. This table divides by the
    retailer's incoming variance, i.e., consumer demand, so it compounds the
    stages below. Values are means across replications.
    """
    table = comparison.stock_points
    consumers = table.filter(pl.col("stock_point") == STAGES[0]).select(
        "scenario",
        "replication",
        pl.col("demand_variance").alias("consumer_variance"),
    )
    return (
        table.join(
            other=consumers,
            on=["scenario", "replication"],
            how="left",
        )
        .group_by(
            "scenario",
            "stock_point",
            maintain_order=True,
        )
        .agg(
            (pl.col("order_variance") / pl.col("consumer_variance"))
            .mean()
            .alias("amplification"),
        )
        .pivot(
            on="stock_point",
            index="scenario",
            values="amplification",
        )
    )


def main():
    output = Path("output/supply_chain")
    comparison = bullwhip_study()
    comparison.export(
        directory=output,
        metric="bullwhip_ratio",
        stock_point="Factory",
    )
    comparison.viewer(
        path=output / "comparison.html",
        metric="bullwhip_ratio",
        stock_point="Factory",
    )
    # The baseline's first replication, for browsing orders and stock by week.
    first = comparison.experiments["Forecast from orders"].runs[0]
    first.export(output / "first-run")
    first.viewer(output / "first-run" / "viewer.html")
    for experiment in comparison.experiments.values():
        for run in experiment.runs:
            assert run.stock_points.get_column("periods").to_list() == [
                WEEKS - WARMUP
            ] * len(STAGES)
    print("\nBullwhip ratio at each stage (order variance / incoming variance)")
    for stage in STAGES:
        print(
            comparison.intervals(
                metric="bullwhip_ratio",
                stock_point=stage,
            ).select(
                "scenario",
                "stock_point",
                "mean",
                "lower",
                "upper",
            )
        )
    print("\nFactory bullwhip ratio relative to forecasting from orders")
    print(
        comparison.differences(
            metric="bullwhip_ratio",
            stock_point="Factory",
        )
    )
    print("\nRetailer fill rate")
    print(
        comparison.intervals(
            metric="fill_rate",
            stock_point="Retailer",
        )
    )
    print("\nOrder variance relative to consumer demand variance")
    print(amplification(comparison))
    capacity = capacity_study()
    capacity.export(
        directory=output / "capacity",
        metric="fill_rate",
        stock_point="Factory",
    )
    capacity.viewer(
        path=output / "capacity" / "comparison.html",
        metric="fill_rate",
        stock_point="Factory",
    )
    columns = ["scenario", "mean", "lower", "upper"]
    for stage in ["Factory", "Distributor"]:
        print(f"\n{stage} fill rate by factory capacity")
        print(
            capacity.intervals(
                metric="fill_rate",
                stock_point=stage,
            ).select(columns)
        )
    print("\nFactory bullwhip ratio by factory capacity")
    print(
        capacity.intervals(
            metric="bullwhip_ratio",
            stock_point="Factory",
        ).select(columns)
    )
    # A brewhouse job's flow time runs from its order to its last case. The
    # two-week scenario brews nothing, so it has no observed runs.
    print("\nBrewhouse lead time in weeks")
    print(capacity.intervals("mean_flow_time").select(*columns, "observed_runs"))
    print(f"Reports were written to {output.resolve()}.")


if __name__ == "__main__":
    main()
