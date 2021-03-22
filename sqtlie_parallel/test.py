import boto3
import json
import resource
import time
import decimal
from botocore.client import Config
from threading import Thread
import fcntl
import sqlite3
import os

# S3 session 생성
s3 = boto3.resource('s3')
s3_client = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')

lambda_read_timeout = 300
boto_max_connections = 1000
lambda_config = Config(read_timeout=lambda_read_timeout, max_pool_connections=boto_max_connections,
                       retries={'max_attempts': 0})
lambda_client = boto3.client('lambda', region_name='us-west-2', config=lambda_config)
lambda_name = 'jg-sqlite-pagerank'
bucket = "jg-pagerank-bucket2"

db_name = 'pagerank.db'
db_path = '/mnt/efs/' + db_name


# 주어진 bucket 위치 경로에 파일 이름이 key인 object와 data를 저장합니다.
def write_to_s3(bucket, key):
    s3.Bucket(bucket).put_object(Key=key)


def get_s3_object(bucket, key):
    response = s3_client.get_object(Bucket=bucket, Key=key)
    return json.loads(response['Body'].read().decode())


def invoke_lambda(current_iter, end_iter, remain_page, file):
    '''
    Lambda 함수를 호출(invoke) 합니다.
    '''

    resp = lambda_client.invoke(
        FunctionName=lambda_name,
        InvocationType='Event',
        Payload=json.dumps({
            "current_iter": current_iter,
            "end_iter": end_iter,
            "remain_page": remain_page,
            "file": file,
        })
    )
    return True


def get_past_pagerank(query, conn):
    print('get try')
    conn.cursor().execute(query)
    ret = conn.cursor().fetchall()
    print('get end')
    return ret


def put_efs(page, rank, iter, relation_length, conn):
    print('put try')
    cur = conn.cursor()
    cur.execute('REPLACE INTO pagerank VALUES (?, ?, ?, ?)',
                (page, iter, rank, relation_length))
    print('put commit try')
    conn.commit()
    print('put end')
    return rank


dampen_factor = 0.8


# 랭크를 계산합니다.
def ranking(page_relation, conn):
    rank = 0
    page_query = 'SELECT * FROM pagerank Where '
    for page in page_relation:
        # dynamodb에 올려져 있는 해당 페이지의 rank를 가져옵니다.
        page_query += 'page=' + page + ' OR '
    page_query = page_query[:len(page_query) - 3]
    get_start = time.time()
    past_pagerank = get_past_pagerank(page_query, conn)
    get_time = time.time() - get_start
    for page_data in past_pagerank:
        past_rank = page_data[2]
        relation_length = page_data[3]
        rank += (past_rank / relation_length)
    rank *= dampen_factor
    return rank, get_time


# 각각 페이지에 대하여 rank를 계산하고 dynamodb에 업데이트 합니다.
def ranking_each_page(page, page_relation, iter, remain_page, conn):
    rank_start = time.time()
    rank, get_time = ranking(page_relation, conn)
    page_rank = rank + remain_page
    rank_time = time.time() - rank_start
    put_start = time.time()
    put_efs(page, page_rank, iter, len(page_relation), conn)
    put_time = time.time() - put_start
    return {'iter': iter,
            'page': page,
            'get_time': get_time,
            'rank_time': rank_time,
            'put_time': put_time,
            'page_rank': page_rank,
            'relation_length': len(page_relation)}


def lambda_handler(event, context):
    current_iter = event['current_iter']
    end_iter = event['end_iter']
    remain_page = event['remain_page']
    file = event['file']
    # os.chdir("/mnt/efs")

    page_relations = get_s3_object(bucket, file)
    while current_iter <= end_iter:
        conn = sqlite3.connect(db_path, timeout=30000000, check_same_thread=False)
        cur = conn.cursor()
        cur.execute('pragma journal_mode=wal')
        cur.execute('pragma busy_timeout=10000000;')
        conn.commit()
        for page, page_relation in page_relations.items():
            ranking_result = ranking_each_page(page, page_relation, current_iter, remain_page, conn)
            print(ranking_result)
        current_iter += 1
        conn.close()
