"""
Seed the database with realistic fake data.

Run inside the app container:
docker compose exec app python -m db.seed
"""

import os
import random
from datetime import date, timedelta

from faker import Faker
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL


fake = Faker()

# Fixed seeds make our generated data reproducible.
random.seed(42)
Faker.seed(42)

CUSTOMERS = 200
PRODUCTS = 50
ORDERS = 5000
DAYS_BACK = 730  # 2 years

CITIES = [
    "Mumbai",
    "Delhi",
    "Bengaluru",
    "Chennai",
    "Pune",
    "Hyderabad",
    "Kolkata",
]

SEGMENTS = [
    "retail",
    "wholesale",
    "vip",
]

CATEGORIES = [
    "Electronics",
    "Furniture",
    "Stationery",
    "Apparel",
    "Food",
]

# "completed" appears three times, so it has a higher probability.
STATUSES = [
    "completed",
    "completed",
    "completed",
    "pending",
    "cancelled",
    "refunded",
]


def engine():
    """Create a SQLAlchemy engine using the admin database user."""

    url = URL.create(
        drivername="postgresql+psycopg",
        username=os.environ["POSTGRES_ADMIN_USER"],
        password=os.environ["POSTGRES_ADMIN_PASSWORD"],
        host=os.environ.get("POSTGRES_HOST", "db"),
        port=int(os.environ.get("POSTGRES_PORT", 5432)),
        database=os.environ["POSTGRES_DB"],
    )

    return create_engine(url, future=True)


def main() -> None:
    eng = engine()

    with eng.begin() as conn:

        # Make the seed script re-runnable.
        # Tables are truncated in FK-safe order.
        conn.execute(
            text(
                "TRUNCATE order_items, orders, products, customers "
                "RESTART IDENTITY CASCADE"
            )
        )

        # ---------------------------------------------------------
        # Customers
        # ---------------------------------------------------------

        for _ in range(CUSTOMERS):
            conn.execute(
                text(
                    """
                    INSERT INTO customers
                        (name, city, segment, created_at)
                    VALUES
                        (:n, :c, :s, :d)
                    """
                ),
                {
                    "n": fake.name(),
                    "c": random.choice(CITIES),
                    "s": random.choice(SEGMENTS),
                    "d": fake.date_between(
                        start_date="-3y",
                        end_date="today",
                    ),
                },
            )

        # ---------------------------------------------------------
        # Products
        # ---------------------------------------------------------

        for _ in range(PRODUCTS):
            conn.execute(
                text(
                    """
                    INSERT INTO products
                        (name, category, price)
                    VALUES
                        (:n, :c, :p)
                    """
                ),
                {
                    "n": fake.catch_phrase()[:40],
                    "c": random.choice(CATEGORIES),
                    "p": round(random.uniform(5, 500), 2),
                },
            )

        # ---------------------------------------------------------
        # Orders + order items
        # ---------------------------------------------------------

        today = date.today()
        start = today - timedelta(days=DAYS_BACK)

        for _ in range(ORDERS):

            order_date = fake.date_between(
                start_date=start,
                end_date=today,
            )

            order_id = conn.execute(
                text(
                    """
                    INSERT INTO orders
                        (customer_id, order_date, status)
                    VALUES
                        (:cid, :d, :s)
                    RETURNING id
                    """
                ),
                {
                    "cid": random.randint(1, CUSTOMERS),
                    "d": order_date,
                    "s": random.choice(STATUSES),
                },
            ).scalar_one()

            # Each order contains between 1 and 4 products.
            for _ in range(random.randint(1, 4)):

                product_id = random.randint(1, PRODUCTS)

                price = conn.execute(
                    text(
                        "SELECT price FROM products WHERE id = :id"
                    ),
                    {"id": product_id},
                ).scalar_one()

                conn.execute(
                    text(
                        """
                        INSERT INTO order_items
                            (order_id, product_id, quantity, unit_price)
                        VALUES
                            (:o, :p, :q, :u)
                        """
                    ),
                    {
                        "o": order_id,
                        "p": product_id,
                        "q": random.randint(1, 5),
                        "u": float(price),
                    },
                )

    print(
        f"Seeded {CUSTOMERS} customers, "
        f"{PRODUCTS} products, "
        f"{ORDERS} orders."
    )


if __name__ == "__main__":
    main()