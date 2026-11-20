import os
import random
from datetime import date, timedelta
import psycopg
from faker import Faker
from dotenv import load_dotenv

SNAPSHOT_DATE = date(2026, 11, 19)
load_dotenv()
fake = Faker()
fake.seed_instance(5861)
random.seed(5861)


def get_connection(db_name: str):
    return psycopg.connect(
        dbname=db_name,
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD"),
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=os.getenv("POSTGRES_PORT", "5436"),
    )


# ==========================================
# DATABASE 1: TRANSACTIONS GENERATORS
# ==========================================

def generate_customers(count: int) -> list[tuple]:
    customers = []
    for i in range(count):
        gender = random.choice(["F", "M"])
        customers.append((f"{fake.user_name()[:45]}_{i}",
                          fake.first_name_female()[:50] if gender == "F" else fake.first_name_male()[:50],
                          fake.last_name()[:50],
                          random.randint(18,90),
                          gender,
                          fake.address().replace("\n",",")[:255],
                          fake.company()[:50] if random.random() > 0.33 else None))
    return customers


def generate_products() -> list[tuple]:

    products = []
    prod_names = ["Monitor", "Keyboard", "Mouse", "Webcam", "Router", "SSD",
                              "Headphones", "Speaker", "Microphone", "Soundbar", "Earbuds",
                              "Desk", "Chair", "Lamp", "Bookshelf", "Organizer", "USB-C Hub",
                              "Laptop Stand", "Charger", "Backpack", "Case"]
    for name in prod_names:
        parent_date = fake.date_between_dates(
            date_start=date(2022, 1, 1),
            date_end=SNAPSHOT_DATE,
        )
        price = round(random.uniform(1.00, 9999.99), 2)
        products.append((name,
                        price,
                        parent_date,
                        round(random.uniform(1.00, price), 2)))
    return products


def generate_transactions(count: int, customers: list[tuple], products: list[tuple]) -> list[tuple]:
    transactions = []
    for i in range(count):
        product = products[random.randint(0, len(products)-1)]
        parent_date = product[2]
        child_date = fake.date_between_dates(
            date_start=parent_date,
            date_end=SNAPSHOT_DATE,
        )
        transactions.append((fake.unique.uuid4(),
                             product[0],
                             customers[random.randint(0, len(customers)-1)][0],
                             child_date,
                             random.randint(1, 1000)))
    return transactions


# ==========================================
# DATABASE 2: SUBSCRIPTIONS GENERATORS
# ==========================================

def generate_users(count: int) -> list[tuple]:
    users = []
    for i in range(count):
        parent_date = fake.date_between_dates(
                    date_start=date(2022, 1, 1),
                    date_end=SNAPSHOT_DATE,
        )
        gender = random.choice(["F", "M"])
        users.append((f"{fake.user_name()[:45]}_{i}",
                      fake.first_name_female()[:50] if gender == "F" else fake.first_name_male()[:50],
                      fake.last_name()[:50],
                      random.randint(18, 90),
                      gender,
                      parent_date))
    return users


def generate_plans() -> list[tuple]:
    plans = [
        ('Basic Monthly', 12.59, 'monthly'),
        ('Basic Annual', 139.08, 'annual'),
        ('Complete Monthly', 19.21, 'monthly'),
        ('Complete Annual', 219.48, 'annual'),
        ('Premium Monthly', 29.19, 'monthly'),
        ('Premium Annual', 338.28, 'annual')
    ]
    return plans


def generate_subscriptions(count: int, users: list[tuple], plans: list[tuple]) -> list[tuple]:
    subscriptions = []
    for i in range(count):
        user = users[random.randint(0, len(users)-1)]
        parent_date = user[5]
        child_date = fake.date_between_dates(
            date_start=parent_date,
            date_end=SNAPSHOT_DATE,
        )

        parent_date2 = child_date
        child_date2 = fake.date_between_dates(
            date_start=parent_date2,
            date_end=SNAPSHOT_DATE,
        )

        subscriptions.append((fake.unique.uuid4(),
                              user[0],
                              child_date,
                              child_date2 if random.random() > 0.5 else None,
                              plans[random.randint(0, len(plans)-1)][0]))
    return subscriptions


def generate_payments(count: int, subscriptions: list[tuple], plans: list[tuple]) -> list[tuple]:
    payments = []
    p_methods = ['card', 'bank_transfer', 'paypal', 'apple_pay', 'google_pay', 'cash']
    status = ['paid', 'pending', 'cancelled', 'failed', 'refunded']
    for i in range(count):
        subscription = subscriptions[random.randint(0, len(subscriptions)-1)]
        parent_date = subscription[2]
        child_date = fake.date_between_dates(
            date_start=parent_date,
            date_end=SNAPSHOT_DATE,
        )
        
        payments.append((fake.unique.uuid4(),
                         subscription[0],
                         p_methods[random.randint(0, len(p_methods)-1)],
                         status[0] if random.random() > 0.2 else status[random.randint(1, len(status)-1)],
                         child_date
                         ))
    return payments


# ==========================================
# EXECUTION & BATCH INSERTION
# ==========================================

def populate_transactions_db():
    conn = get_connection("transactions")
    try:
        with conn.cursor() as cur:
            customers = generate_customers(10000)
            products = generate_products()
            transactions = generate_transactions(20000, customers, products)
            cur.execute("TRUNCATE TABLE TRANSACTIONS, CUSTOMERS, PRODUCTS CASCADE;")
            cur.executemany("INSERT INTO CUSTOMERS (LOGIN, FIRST_NAME, LAST_NAME, AGE, GENDER, ADDRESS, COMPANY_NAME) VALUES (%s, %s, %s, %s, %s, %s, %s)", customers)
            cur.executemany("INSERT INTO PRODUCTS (NAME, PRICE, RELEASE_DATE, COST_OF_PRODUCTION) VALUES (%s, %s, %s, %s)", products)
            cur.executemany("INSERT INTO TRANSACTIONS (ID, PRODUCT_NAME, CUSTOMER_LOGIN, DATE_OF_TRANSACTION, QUANTITY) VALUES (%s, %s, %s, %s, %s)", transactions)
        conn.commit()
        print("transactions DB populated successfully.")
    except Exception as e:
        conn.rollback()
        print(f"Error populating transactions DB: {e}")
    finally:
        conn.close()


def populate_subscriptions_db():
    conn = get_connection("subscriptions")
    try:
        with conn.cursor() as cur:
            users = generate_users(10000)
            plans = generate_plans()
            subscriptions = generate_subscriptions(15000, users, plans)
            payments = generate_payments(30000, subscriptions, plans)
            cur.execute("TRUNCATE TABLE PAYMENTS, SUBSCRIPTIONS, USERS, PLANS CASCADE;")
            cur.executemany("INSERT INTO USERS (LOGIN, FIRST_NAME, LAST_NAME, AGE, GENDER, SIGNUP_DATE) VALUES (%s, %s, %s, %s, %s, %s)", users)
            cur.executemany("INSERT INTO PLANS (NAME, PRICE, BILLING_PERIOD) VALUES (%s, %s, %s)", plans)
            cur.executemany("INSERT INTO SUBSCRIPTIONS (ID, USER_LOGIN, START_DATE, END_DATE, PLANS_NAME) VALUES (%s, %s, %s, %s, %s)", subscriptions)
            cur.executemany("INSERT INTO PAYMENTS (ID, SUBSCRIPTION_ID, PAYMENT_METHOD, STATUS, PAYMENT_DATE) VALUES (%s, %s, %s, %s, %s)", payments)

        conn.commit()
        print("subscriptions DB populated successfully.")
    except Exception as e:
        conn.rollback()
        print(f"Error populating subscriptions DB: {e}")
    finally:
        conn.close()


if __name__ == "__main__":
    populate_transactions_db()
    populate_subscriptions_db()