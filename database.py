from sqlalchemy import MetaData

# TODO secure the credentials
DATABASE_URL = "postgresql://paymentsystem:paymentsystem@localhost:5432/paymentsystem"
metadata = MetaData()