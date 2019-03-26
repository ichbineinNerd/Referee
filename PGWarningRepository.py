import time
from datetime import datetime, timedelta
from typing import Dict, List

import psycopg2

from config.Config import Config
from models.refwarning import RefWarning

config = Config("config/options.ini")

creation = (
    """
    DROP TABLE IF EXISTS warnings
    """,
    """
    CREATE TABLE IF NOT EXISTS warnings (
        id SERIAL PRIMARY KEY,
        user_id VARCHAR(32) NOT NULL,
        timestamp TIMESTAMP NOT NULL,
        expiration_time TIMESTAMP NOT NULL,
        reason VARCHAR(255)
        )
    """
)


class PGWarningRepository:

    def __init__(self):
        self.conn: psycopg2._psycopg.connection = psycopg2.connect(
            host=config.PG_Host,
            database=config.PG_Database,
            user=config.PG_User,
            password=config.PG_Password
        )
        self.conn.cursor().execute(creation[1])

    def close(self):
        if not self.conn.closed:
            self.conn.close()

    def check_database(self):
        cur: psycopg2._psycopg.cursor = self.conn.cursor()
        test_query = "SELECT id, user_id, timestamp, expiration_time, reason from warnings LIMIT 1"

    def recreate_tables(self):
        cur: psycopg2._psycopg.cursor = self.conn.cursor()
        for command in creation:
            cur.execute(command)
        cur.close()
        self.conn.commit()

    def put_warning(self, warning: RefWarning):
        user_id = warning.user_id
        reason = warning.reason
        timestamp = warning.timestamp
        expiration_time = warning.expiration_time

        insert = "INSERT into warnings(user_id, timestamp, reason, expiration_time) VALUES(%s, %s, %s, %s)"
        cur = self.conn.cursor()

        cur.execute(insert, (user_id, timestamp, reason, expiration_time))
        cur.close()
        self.conn.commit()

    def get_warnings(self, user_id: str) -> List[RefWarning]:
        query = "SELECT * FROM warnings WHERE user_id LIKE %s"
        cur: psycopg2._psycopg.cursor = self.conn.cursor()

        cur.execute(query, (str(user_id),))

        results = cur.fetchall()

        cur.close()
        self.conn.commit()

        warnings = []
        for result in results:
            print(result)
            warnings.append(RefWarning(user_id=result[1], timestamp=result[2], expiration_time=result[3], reason=result[4]))

        return warnings

    def get_active_warnings(self, user_id: str):
        cur: psycopg2._psycopg.cursor = self.conn.cursor()

        query = "SELECT * FROM warnings WHERE user_id LIKE %s AND expiration_time > TIMESTAMP %s"

        cur.execute(query, (str(user_id), str(datetime.now())))

        results = cur.fetchall()

        warnings = [RefWarning(user_id=result[1], timestamp=result[2], expiration_time=result[3], reason=result[4]) for result in results]

        return warnings

    def get_all_warnings(self) -> Dict[str, List[RefWarning]]:
        cur: psycopg2._psycopg.cursor = self.conn.cursor()

        query_ids = "SELECT DISTINCT user_id FROM warnings"
        cur.execute(query_ids)
        user_ids = cur.fetchall()

        warnings = {user_id[0]: [] for user_id in user_ids}

        query_all = "SELECT id, user_id, timestamp, expiration_time, reason FROM warnings ORDER BY user_id"

        cur.execute(query_all)

        results = cur.fetchall()

        for result in results:
            w = RefWarning(user_id=result[1], timestamp=result[2], expiration_time=result[3], reason=result[4])
            warnings[result[1]].append(w)

        return warnings

    def get_all_active_warnings(self) -> Dict[str, List[RefWarning]]:
        cur: psycopg2._psycopg.cursor = self.conn.cursor()

        query_ids = "SELECT DISTINCT user_id FROM warnings"
        cur.execute(query_ids)
        user_ids = cur.fetchall()

        warnings = {user_id[0]: [] for user_id in user_ids}

        query_all = """
        SELECT id, user_id, timestamp, expiration_time, reason FROM warnings 
        WHERE expiration_time > TIMESTAMP %s ORDER BY user_id
        """

        cur.execute(query_all, (str(datetime.now()),))

        results = cur.fetchall()

        for result in results:
            w = RefWarning(user_id=result[1], timestamp=result[2], expiration_time=result[3], reason=result[4])
            warnings[result[1]].append(w)

        cur.close()

        return warnings

    def expire_warnings(self, user_id: str):
        cur: psycopg2._psycopg.cursor = self.conn.cursor()

        query = "UPDATE warnings SET expiration_time = TIMESTAMP %s WHERE user_id LIKE %s"

        cur.execute(query, (datetime.now(), str(user_id)))

        cur.close()

        self.conn.commit()


if __name__ == "__main__":
    p = PGWarningRepository()
    p.check_database()
    p.recreate_tables()

    for i in range(10):
        p.put_warning(RefWarning("user_{}".format(i // 2 +1), datetime.now(), reason="Being a cunt", expiration_time=datetime.now()+timedelta(days=2)))
        time.sleep(0.5)

    print(p.get_active_warnings("user_2"))

    print("<=>")

    p.expire_warnings("user_2")

    print(p.get_active_warnings("user_2"))

    print(">=<")
