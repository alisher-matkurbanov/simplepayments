import datetime
import decimal

from app.database import db
from app.schemas import AccountCreateIn, Currency, ExtendedAccountOut, ReplenishWalletInfo, TransactionType, \
    TransferMoneyOut, TransferMoneyIn
from app.crud import uuid
from app import crud
from app.config import settings
import pytest


@pytest.mark.asyncio
async def test_create_account_with_wallet(monkeypatch):
    await db.connect()
    try:
        test_uuid = uuid.uuid4()
        test_name = "testname"
        account = AccountCreateIn(name=test_name)
        
        def mock_uuid4():
            return test_uuid
        
        monkeypatch.setattr(uuid, "uuid4", mock_uuid4)
        await crud.create_account_with_wallet(account)
        
        # check account in database
        select_account_with_wallet = (
            "SELECT "
            "account.id as account_id, account.name, "
            "account.created_at, wallet.id as wallet_id, "
            "wallet.currency, wallet.amount "
            "FROM account JOIN wallet "
            "ON wallet.account_id = account.id  "
            "WHERE  account.id = :account_id;"
        )
        values = {"account_id": test_uuid}
        row = await db.fetch_one(query=select_account_with_wallet, values=values)
        assert row is not None
        assert row["wallet_id"] == test_uuid
        assert row["name"] == test_name
        assert row["currency"] == Currency.USD.value
        assert row["amount"] == 0
    finally:
        await db.disconnect()


@pytest.mark.asyncio
async def test_get_account_with_wallet():
    await db.connect()
    try:
        account_uuid = uuid.uuid4()
        wallet_uuid = uuid.uuid4()
        name = "testname"
        amount = decimal.Decimal("9999999.12")
        currency = Currency.USD
        created_at = datetime.datetime.now(tz=datetime.timezone.utc)
        
        expected = ExtendedAccountOut(
            account_id=account_uuid,
            name=name,
            wallet_id=wallet_uuid,
            currency=currency,
            amount=amount,
            created_at=created_at,
        )
        insert_account = "INSERT INTO account(id, name, created_at) " \
                         "VALUES (:account_id, :name, :created_at);"
        insert_wallet = "INSERT INTO wallet(id, account_id, amount, currency) " \
                        "VALUES (:wallet_id, :account_id, :amount, :currency);"
        values = {"account_id": account_uuid, "name": name, "created_at": created_at}
        await db.execute(insert_account, values)
        values = {
            "account_id": account_uuid,
            "wallet_id": wallet_uuid,
            "amount": amount,
            "currency": currency.value
        }
        await db.execute(insert_wallet, values)
        
        account = await crud.get_account_with_wallet(account_uuid)
        
        # check account in database
        
        assert account == expected
    finally:
        await db.disconnect()


@pytest.mark.asyncio
async def test_transfer():
    await db.connect()
    try:
        from_account_id = uuid.uuid4()
        from_name = "testname1"
        from_amount = decimal.Decimal("9999999.12")
        from_wallet_id = uuid.uuid4()
        from_created_at = datetime.datetime.now(tz=datetime.timezone.utc)
        
        to_account_id = uuid.uuid4()
        to_name = "testname2"
        to_amount = decimal.Decimal("12.12")
        to_wallet_id = uuid.uuid4()
        to_created_at = datetime.datetime.now(tz=datetime.timezone.utc)
        
        transfer_amount = decimal.Decimal("789.98")
        currency = Currency.USD
        input = TransferMoneyIn(
            from_wallet_id=from_wallet_id,
            from_currency=currency,
            to_wallet_id=to_wallet_id,
            to_currency=currency,
            amount=transfer_amount
        )
        expected = TransferMoneyOut(
            from_wallet_id=from_wallet_id,
            from_amount=from_amount - transfer_amount,
            from_currency=currency,
            to_wallet_id=to_wallet_id,
            to_amount=to_amount + transfer_amount,
            to_currency=currency,
        )
        # add 2 accounts
        insert_account = "INSERT INTO account(id, name, created_at) " \
                         "VALUES (:account_id, :name, :created_at);"
        insert_wallet = "INSERT INTO wallet(id, account_id, amount, currency) " \
                        "VALUES (:wallet_id, :account_id, :amount, :currency);"
        values = {"account_id": to_account_id, "name": to_name, "created_at": to_created_at}
        await db.execute(insert_account, values)
        values = {"account_id": from_account_id, "name": from_name, "created_at": from_created_at}
        await db.execute(insert_account, values)
        values = {
            "account_id": from_account_id,
            "wallet_id": from_wallet_id,
            "amount": from_amount,
            "currency": currency.value
        }
        await db.execute(insert_wallet, values)
        values = {
            "account_id": to_account_id,
            "wallet_id": to_wallet_id,
            "amount": to_amount,
            "currency": currency.value
        }
        await db.execute(insert_wallet, values)
        
        # perform transfer
        actual = await crud.transfer(input)
        
        # get money in wallets
        select_wallet = "SELECT amount FROM wallet WHERE id = :wallet_id"
        from_wallet = await db.fetch_one(select_wallet, {"wallet_id": from_wallet_id})
        to_wallet = await db.fetch_one(select_wallet, {"wallet_id": to_wallet_id})
        # get transactions
        select_transaction = "SELECT id, type FROM transaction ORDER BY id DESC LIMIT 1;"
        transaction = await db.fetch_one(select_transaction)
        select_posting = "SELECT amount, wallet_id, currency FROM posting WHERE transaction_id = :tid;"
        posting = await db.fetch_all(select_posting, {"tid": transaction["id"]})
        
        # check return value
        assert actual == expected
        # check money in wallets
        assert from_wallet["amount"] == from_amount - transfer_amount
        assert to_wallet["amount"] == to_amount + transfer_amount
        # check transaction added
        assert transaction["type"] == TransactionType.transfer.value
        assert posting[0]["amount"] == -transfer_amount
        assert posting[0]["wallet_id"] == from_wallet_id
        assert posting[1]["amount"] == transfer_amount
        assert posting[1]["wallet_id"] == to_wallet_id
    finally:
        await db.disconnect()


@pytest.mark.asyncio
async def test_transfer_exceptions():
    await db.connect()
    try:
        from_account_id = uuid.uuid4()
        from_name = "testname1"
        from_amount = decimal.Decimal("9999999.12")
        from_wallet_id = uuid.uuid4()
        from_created_at = datetime.datetime.now(tz=datetime.timezone.utc)
        
        to_account_id = uuid.uuid4()
        to_name = "testname2"
        to_amount = settings.max_amount
        to_wallet_id = uuid.uuid4()
        to_created_at = datetime.datetime.now(tz=datetime.timezone.utc)
        
        transfer_amount = decimal.Decimal(1)
        currency = Currency.USD
        
        input_1 = TransferMoneyIn(
            from_wallet_id=from_wallet_id,
            from_currency=Currency.USD,
            to_wallet_id=to_wallet_id,
            to_currency=Currency.USD,
            amount=transfer_amount
        )
        # check first wallet
        with pytest.raises(crud.CRUDException) as not_found_error_info:
            await crud.transfer(input_1)
        values = dict(wallet_id=from_wallet_id, currency=currency.value)
        etext = f"wallet with {values} not found"
        assert not_found_error_info.value.message == etext
        
        insert_account = "INSERT INTO account(id, name, created_at) " \
                         "VALUES (:account_id, :name, :created_at);"
        insert_wallet = "INSERT INTO wallet(id, account_id, amount, currency) " \
                        "VALUES (:wallet_id, :account_id, :amount, :currency);"
        values = {"account_id": to_account_id, "name": to_name, "created_at": to_created_at}
        await db.execute(insert_account, values)
        values = {"account_id": from_account_id, "name": from_name, "created_at": from_created_at}
        await db.execute(insert_account, values)
        values = {
            "account_id": from_account_id,
            "wallet_id": from_wallet_id,
            "amount": from_amount,
            "currency": currency.value
        }
        await db.execute(insert_wallet, values)
        
        # check second wallet
        with pytest.raises(crud.CRUDException) as not_found_error_info:
            await crud.transfer(input_1)
        values = dict(wallet_id=to_wallet_id, currency=currency.value)
        etext = f"wallet with {values} not found"
        assert not_found_error_info.value.message == etext
        
        values = {
            "account_id": to_account_id,
            "wallet_id": to_wallet_id,
            "amount": to_amount,
            "currency": currency.value
        }
        await db.execute(insert_wallet, values)
        # check max amount exception
        with pytest.raises(crud.CRUDException) as max_amount_error:
            await crud.transfer(input_1)
        
        select_wallet = "SELECT amount FROM wallet WHERE id = :wallet_id"
        from_wallet = await db.fetch_one(select_wallet, {"wallet_id": from_wallet_id})
        to_wallet = await db.fetch_one(select_wallet, {"wallet_id": to_wallet_id})
        etext1 = (f"can't transfer to {to_wallet_id}; "
                  f"resulting amount is greater that max amount = {settings.max_amount}; "
                  f"current amount = {to_wallet['amount']}")
        etext2 = (
            f"can't transfer {transfer_amount} {currency.value} "
            f"from wallet {from_wallet_id}: "
            f"not enough amount"
        )
        # check money didn't changed
        assert from_wallet["amount"] == from_amount
        assert to_wallet["amount"] == to_amount
        assert max_amount_error.value.message == etext1
        
        # check another exception
        await db.execute("UPDATE wallet SET amount = 0 WHERE id = :from_wallet_id",
                         {"from_wallet_id": from_wallet_id})
        from_wallet = await db.fetch_one(select_wallet, {"wallet_id": from_wallet_id})
        with pytest.raises(crud.CRUDException) as negative_amount_error:
            await crud.transfer(input_1)
        assert from_wallet["amount"] == 0
        # money on second wallet didn't changed
        assert to_wallet["amount"] == to_amount
        assert negative_amount_error.value.message == etext2
    finally:
        await db.disconnect()


@pytest.mark.asyncio
async def test_replenish():
    await db.connect()
    try:
        account_id = uuid.uuid4()
        wallet_id = uuid.uuid4()
        name = "testname"
        amount = decimal.Decimal("9999999.12")
        replenish_amount = decimal.Decimal("789.98")
        currency = Currency.USD
        created_at = datetime.datetime.now(tz=datetime.timezone.utc)
        wallet_info_in = ReplenishWalletInfo(
            wallet_id=wallet_id, amount=replenish_amount, currency=currency
        )
        expected_wallet_info = ReplenishWalletInfo(
            wallet_id=wallet_id, amount=replenish_amount + amount, currency=currency
        )
        # add account
        insert_account = "INSERT INTO account(id, name, created_at) " \
                         "VALUES (:account_id, :name, :created_at);"
        insert_wallet = "INSERT INTO wallet(id, account_id, amount, currency) " \
                        "VALUES (:wallet_id, :account_id, :amount, :currency);"
        values = {"account_id": account_id, "name": name, "created_at": created_at}
        await db.execute(insert_account, values)
        values = {
            "account_id": account_id,
            "wallet_id": wallet_id,
            "amount": amount,
            "currency": currency.value
        }
        await db.execute(insert_wallet, values)
        
        wallet_info_out = await crud.replenish(wallet_info_in)
        # check money in account
        select_wallet = "SELECT amount, currency FROM wallet WHERE id = :wallet_id"
        replenished_wallet = await db.fetch_one(select_wallet, {"wallet_id": wallet_id})
        # check transactions
        select_transaction = "SELECT id, type FROM transaction ORDER BY id DESC LIMIT 1;"
        transaction = await db.fetch_one(select_transaction)
        select_posting = "SELECT amount, wallet_id, currency FROM posting WHERE transaction_id = :tid;"
        posting = await db.fetch_one(select_posting, {"tid": transaction["id"]})
        
        assert wallet_info_out == expected_wallet_info
        assert replenished_wallet["amount"] == expected_wallet_info.amount
        assert replenished_wallet["currency"] == expected_wallet_info.currency.value
        assert transaction["type"] == TransactionType.replenish.value
        assert posting["amount"] == replenish_amount
        assert posting["wallet_id"] == wallet_id
        assert posting["currency"] == currency.value
    finally:
        await db.disconnect()


@pytest.mark.asyncio
async def test_replenish_exceptions():
    await db.connect()
    try:
        account_id = uuid.uuid4()
        wallet_id = uuid.uuid4()
        name = "testname"
        amount = settings.max_amount
        replenish_amount = decimal.Decimal(1)
        currency = Currency.USD
        created_at = datetime.datetime.now(tz=datetime.timezone.utc)
        wallet_info_in = ReplenishWalletInfo(
            wallet_id=wallet_id, amount=replenish_amount, currency=currency
        )
        # wallet not found
        with pytest.raises(crud.CRUDException) as not_found_error_info:
            await crud.replenish(wallet_info_in)
        values = dict(wallet_id=wallet_id, currency=currency.value)
        etext = f"wallet with {values} not found"
        assert not_found_error_info.value.message == etext
        
        # add account
        insert_account = "INSERT INTO account(id, name, created_at) " \
                         "VALUES (:account_id, :name, :created_at);"
        insert_wallet = "INSERT INTO wallet(id, account_id, amount, currency) " \
                        "VALUES (:wallet_id, :account_id, :amount, :currency);"
        values = {"account_id": account_id, "name": name, "created_at": created_at}
        await db.execute(insert_account, values)
        values = {
            "account_id": account_id,
            "wallet_id": wallet_id,
            "amount": amount,
            "currency": currency.value
        }
        await db.execute(insert_wallet, values)
        
        # can't replenish - max amount exception
        with pytest.raises(crud.CRUDException) as max_amount_error_info:
            await crud.replenish(wallet_info_in)
        etext = (
            f"can't replenish to {wallet_id}; "
            f"resulting amount is greater that max amount = {settings.max_amount}; "
            f"current amount = {amount}"
        )
        assert max_amount_error_info.value.message == etext
        # check money in account
        select_wallet = "SELECT amount, currency FROM wallet WHERE id = :wallet_id"
        replenished_wallet = await db.fetch_one(select_wallet, {"wallet_id": wallet_id})
        
        # money haven't changed
        assert replenished_wallet["amount"] == amount
    finally:
        await db.disconnect()
