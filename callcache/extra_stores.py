import time
from typing import Any, Iterable, Literal, Optional, Tuple

try:
    import boto3
except ModuleNotFoundError:
    pass

try:
    import pymemcache.client.hash
except ModuleNotFoundError:
    pass

try:
    from google.cloud import firestore
except ModuleNotFoundError:
    pass


class DynamoDBStore:
    def __init__(self, table_name: str):
        self.table_name = table_name
        self.store = boto3.resource("dynamodb").Table(self.table_name)
        try:
            self.store.load()
        except:  # noqa: E722
            self.create_store()
        self.stats = {"hit": 0, "miss": 0, "bad_input": 0, "bad_output": 0}

    def create_store(self) -> None:
        dynamodb = boto3.resource("dynamodb")
        self.store = dynamodb.create_table(
            TableName=self.table_name,
            KeySchema=[{"AttributeName": "key", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "key", "AttributeType": "S"}],
            ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
        )
        self.store.meta.client.get_waiter("table_exists").wait(
            TableName=self.table_name
        )

    def set(
        self,
        key: str,
        value: Any,
        expire: float = 2_635_200,
        expanded_key: Optional[str] = None,
    ) -> Literal[True]:
        expires = int(time.time()) + expire
        self.store.put_item(
            Item={
                "key": key,
                "expires": expires,
                "response": value,
                "request": expanded_key,
            }
        )
        return True

    def get(self, key: str) -> Any:
        try:
            item = self.store.get_item(Key={"key": key})
            value = item["Item"]["response"]
            expires = item["Item"]["expires"]
            if expires > time.time():
                self.stats["hit"] += 1
                return value
        except:  # noqa: E722
            pass
        self.stats["miss"] += 1
        return None

    def clear(self) -> None:
        with self.store.batch_writer() as batch:
            for item in self.store.scan()["Items"]:
                batch.delete_item(Key={"key": item["key"]})
        self.stats = {"hit": 0, "miss": 0, "bad_input": 0, "bad_output": 0}


class FirestoreStore:
    def __init__(self, table_name: str):
        self.table_name = table_name
        self.store = firestore.Client().collection(self.table_name)
        self.stats = {"hit": 0, "miss": 0, "bad_input": 0, "bad_output": 0}

    def set(
        self,
        key: str,
        value: Any,
        expire: float = 2_635_200,
        expanded_key: Optional[str] = None,
    ) -> Literal[True]:
        expires = int(time.time()) + expire
        self.store.document(key).set(
            {
                "key": key,
                "expires": expires,
                "response": value,
                "request": expanded_key,
            }
        )
        return True

    def get(self, key: str) -> Any:
        try:
            item = self.store.document(key).get().to_dict()
            value = item["response"]
            expires = item["expires"]
            if expires > time.time():
                self.stats["hit"] += 1
                return value
        except:  # noqa: E722
            pass
        self.stats["miss"] += 1
        return None

    def clear(self) -> None:
        for document in self.store.stream():
            document.reference.delete()
        self.stats = {"hit": 0, "miss": 0, "bad_input": 0, "bad_output": 0}


class MemcacheStore:
    def __init__(
        self, servers: Iterable[Tuple[str, int]] = (("localhost", 11211),)
    ) -> None:
        self.client = pymemcache.client.hash.HashClient(servers)
        self.stats = {"hit": 0, "miss": 0, "bad_input": 0, "bad_output": 0}
        self.set = self.client.set

    def clear(self) -> Any:
        self.stats = {"hit": 0, "miss": 0, "bad_input": 0, "bad_output": 0}
        return self.client.flush_all()

    def get(self, key: str) -> Any:
        value = self.client.get(key)
        if value is None:
            self.stats["miss"] += 1
        else:
            self.stats["hit"] += 1
        return value and value.decode("utf-8")
