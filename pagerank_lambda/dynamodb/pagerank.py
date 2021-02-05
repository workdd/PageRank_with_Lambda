import boto3
import json
import resource
import time
import decimal
from botocore.client import Config
from threading import Thread

# S3 session 생성
s3 = boto3.resource('s3')
s3_client = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')
db_name = 'jg-pagerank'
rank_table = dynamodb.Table(db_name)

lambda_read_timeout = 300
boto_max_connections = 1000
lambda_config = Config(read_timeout=lambda_read_timeout, max_pool_connections=boto_max_connections)
lambda_client = boto3.client('lambda', config=lambda_config)
lambda_name = 'pagerank'
bucket = "jg-pagerank-bucket"


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
        InvocationType='RequestResponse',
        Payload=json.dumps({
            "current_iter": current_iter,
            "end_iter": end_iter,
            "remain_page": remain_page,
            "file": file,
        })
    )


def get_past_pagerank(t, page):
    past_pagerank = t.get_item(Key={'page': str(page)})
    return past_pagerank['Item']


def put_dynamodb_items(page, iter, rank, relation_length):
    rank_table.put_item(
        Item={
            'iter': iter,
            'page': str(page),
            'rank': decimal.Decimal(str(rank)),
            'relation_length': decimal.Decimal(str(relation_length)),
        }
    )


dampen_factor = 0.8


# 랭크를 계산합니다.
def ranking(page_relation):
    leave_page = 0
    for page in page_relation:
        # dynamodb에 올려져 있는 해당 페이지의 rank를 가져옵니다.
        try:
            past_info = get_past_pagerank(rank_table, page)
            leave_page += float(past_info['rank']) / float(past_info['relation_length'])
        except:
            print('error page', page)
            pass
    leave_page *= dampen_factor
    return leave_page


# iter > 0 인 경우 실행 됩니다.
# 각각 페이지에 대하여 rank를 계산하고 dynamodb에 업데이트 합니다.
def each_page(page, page_relation, iter, remain_page):
    page_rank = ranking(page_relation) + remain_page
    put_dynamodb_items(page, iter, page_rank, len(page_relation))
    return True


def lambda_handler(event, context):
    current_iter = event['current_iter']
    end_iter = event['end_iter']
    remain_page = event['remain_page']
    file = event['file']
    page_relations = get_s3_object(bucket, file)
    for page, page_relation in page_relations.items():
        each_page(page, page_relation, current_iter, remain_page)
    # current_iter = end_iter이 되기 전 까지 다음 iteration 람다를 invoke합니다.
    if current_iter < end_iter:
        print(file, '범위', current_iter, '완료')
        invoke_lambda(current_iter + 1, end_iter, remain_page, file)
    return True
