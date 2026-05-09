from . import TorriCLI
import uuid
import os
import json
from confluent_kafka import Consumer, KafkaError
from shared.merger_models import MergeRequest, MergeAction
from torri.kafka.producer import KafkaProducerClient

def run_server(args):
    print("🚀 Torri Test Scheduler Booting Up...")
    producer = KafkaProducerClient(os.getenv("KAFKA_SERVER", "localhost:9094"))
    input_topic = os.getenv("KAFKA_MERGER_INPUT_TOPIC", "merger-requests")
    output_topic = os.getenv("KAFKA_MERGER_OUTPUT_TOPIC", "merger-responses")

    test_requests = [
        # Job 1: ISOLATED - Single ref starting fresh from origin/master
        MergeRequest(
            job_id=f"job-{uuid.uuid4().hex[:8]}",
            target_repository="gerrit:libraries/common-utils.git",
            base_branch="master",
            patchset_refs=["refs/changes/01/1/1"],
            action=MergeAction.SPECULATIVE_MERGE,
            strategy="rebase"
        ),
        
        # Job 2: ISOLATED - Different single ref, also starts fresh from origin/master  
        MergeRequest(
            job_id=f"job-{uuid.uuid4().hex[:8]}",
            target_repository="gerrit:libraries/common-utils.git",
            base_branch="master",
            patchset_refs=["refs/changes/02/2/1"],
            action=MergeAction.SPECULATIVE_MERGE,
            strategy="merge"
        ),
        
        # Job 3: STACKED - Multiple refs composed together!
        # Starts from origin/master, then:
        # 1. Rebase refs/changes/01/1/1 on origin/master
        # 2. On top of that result, cherry-pick refs/changes/02/2/2
        # Result: single synthetic ref with BOTH changes stacked
        MergeRequest(
            job_id=f"job-{uuid.uuid4().hex[:8]}",
            target_repository="gerrit:libraries/common-utils.git",
            base_branch="master",
            patchset_refs=["refs/changes/01/1/1", "refs/changes/02/2/1","refs/changes/03/3/1"],
            action=MergeAction.SPECULATIVE_MERGE,
            strategy="rebase"  # Strategy applies to ALL refs in this stack
        ),

        ]

    for i, req in enumerate(test_requests):
        print(f"📤 Sending Request {i+1}: {req.job_id} for repo: {req.target_repository.split('/')[-1]} with refs: {req.patchset_refs}")
        producer.send_message(input_topic, key=req.job_id, value=req.model_dump(exclude_none=True))
    
    producer.flush()
    print("\n👂 Waiting for responses from Merger...\n")

    # Start consumer to read responses
    consumer_config = {
        'bootstrap.servers': os.getenv("KAFKA_SERVER", "localhost:9094"),
        'group.id': "scheduler-test-group",
        'auto.offset.reset': 'earliest'
    }
    consumer = Consumer(consumer_config)
    consumer.subscribe([output_topic])

    responses_received = 0
    try:
        while responses_received < len(test_requests):
            msg = consumer.poll(timeout=1.0)
            if msg is None:
                continue
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    continue
                print(f"❌ Consumer error: {msg.error()}")
                continue
            
            raw_data = json.loads(msg.value().decode('utf-8'))
            print(f"📥 Received Response for Job [{raw_data.get('job_id')}]:")
            print(f"   - Status: {raw_data.get('status')}")
            print(f"   - Synthetic Ref (Merged Commit Hash): {raw_data.get('merged_commit_hash')}")
            print(f"   - Error: {raw_data.get('error_message')}\n")
            responses_received += 1
            
            consumer.commit(msg)
    except KeyboardInterrupt:
        print("Stopped.")
    finally:
        consumer.close()

def main():
    cli = TorriCLI(description="Torri Scheduler (Test Mode)")
    cli.run(run_server)

if __name__ == "__main__":
    main()
