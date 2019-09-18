# Run the translation in rabbit
import pika
import sys
import pickle
import ast
import base64
import json
import os
from adl_func_backend.xAODlib.exe_atlas_xaod_hash_cache import use_executor_xaod_hash_cache, CacheExeException
import logging
import inspect
import zipfile
import os

def zipdir(path: str, zip_handle: zipfile.ZipFile):
    # zip_handle is zipfile handle
    for root, _, files in os.walk(path):
        for file in files:
            zip_handle.write(os.path.join(root, file), file)

def process_message(ch, method, properties, body):
    'Message comes in off the queue. We deal with it.'
    info = json.loads(body)
    hash = info['hash']
    a = pickle.loads(base64.b64decode(info['ast']))
    if a is None or not isinstance(a, ast.AST):
        print (f"Body of message wasn't an ast: {a}")

    # Now do the translation.
    ch.basic_publish(exchange='', routing_key='status_change_state', body=json.dumps({'hash': hash, 'phase': 'generating_cpp'}))
    try:
        r = use_executor_xaod_hash_cache (a, '/cache')
        ch.basic_publish(exchange='', routing_key='status_change_state', body=json.dumps({'hash': hash, 'phase': 'finished_cpp'}))

        # Decide how many jobs we will split things into.
        # For now, we do one job only.
        ch.basic_publish(exchange='', routing_key='status_number_jobs', body=json.dumps({'hash': hash, 'njobs': 1}))

        # Zip up everything in the directory - we are going to ship it as part of the message. To send it we are going to base64 it.
        z_filename = f'/tmp/{r.hash}.zip'
        zip_h = zipfile.ZipFile(z_filename, 'w', zipfile.ZIP_DEFLATED)
        zipdir(f'/cache/{r.hash}', zip_h)
        zip_h.close()

        with open(z_filename, 'rb') as b_in:
            zip_data = b_in.read()
        zip_data_b64 = bytes.decode(base64.b64encode(zip_data))

        # Create the JSON message that can be sent on to the next stage.
        # Are now carrying along two hashes - one that identifies this query and everything associated with it.
        # And a second that is for the source code for this query (which is independent of the files we are going to process).
        filebase, extension = os.path.splitext(os.path.basename(r.output_filename))
        msg = {
            'hash': hash,
            'hash_source': r.hash,
            'main_script': r.main_script,
            'files': r.filelist,
            'output_file': f'{hash}/{filebase}_001{extension}',
            'treename': r.treename,
            'file_data': zip_data_b64
        }
        ch.basic_publish(exchange='', routing_key='run_cpp', body=json.dumps(msg))

    except BaseException as e:
        # We crashed. No idea why, but lets log it, and give up on this request.
        frame = inspect.trace()[-1]
        where_raised = f'Exception raised in function {frame[3]} ({frame[1]}:{frame[2]}).'
        ch.basic_publish(exchange='', routing_key='status_change_state', body=json.dumps({'hash': hash, 'phase': f'crashed'}))
        ch.basic_publish(exchange='', routing_key='crashed_request', body=json.dumps({'hash':hash, 'message':'While translating python to C++', 'log': [where_raised, f'  {str(e)}']}))

    # Done! Take this off the queue now.
    ch.basic_ack(delivery_tag=method.delivery_tag)

def listen_to_queue(rabbit_server:str, rabbit_user:str, rabbit_pass:str):
    'Look for jobs to come off a queue and send them on'

    # Connect and setup the queues we will listen to and push once we've done.
    if rabbit_pass in os.environ:
        rabbit_pass = os.environ[rabbit_pass]
    credentials = pika.PlainCredentials(rabbit_user, rabbit_pass)
    connection = pika.BlockingConnection(pika.ConnectionParameters(host=rabbit_server, credentials=credentials))
    channel = connection.channel()
    channel.queue_declare(queue='parse_cpp')
    channel.queue_declare(queue='run_cpp')
    channel.queue_declare(queue='status_change_state')
    channel.queue_declare(queue='status_number_jobs')


    channel.basic_consume(queue='parse_cpp', on_message_callback=process_message, auto_ack=False)

    # We are setup. Off we go. We'll never come back.
    channel.start_consuming()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    bad_args = len(sys.argv) != 4
    if bad_args:
        print ("Usage: python translate_ast_to_cpp_rabbit.py <rabbit-mq-node-address> <rabbit-username> <rabbit-password>")
    else:
        listen_to_queue(sys.argv[1], sys.argv[2], sys.argv[3])
