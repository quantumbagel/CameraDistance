import math
import time
import logging
import kafka
from kafka import KafkaConsumer

VALID_STATUS = ["off", "on", "auto"]


class Watcher:
    """
    A class to watch for changes to the dronetracker-command Kafka topic
    """

    def __init__(self, connection: str, command_topic: str):
        """
        Initialize the Watcher class
        :param connection: Kafka connection IP
        :param command_topic: Kafka topic to watch for
        """
        self.connection = connection  # Connection IP
        self.consumer = KafkaConsumer(bootstrap_servers=[connection])
        self.topic = command_topic
        self.consumer.subscribe([self.topic])
        self.log = logging.getLogger('Watcher')
        self.status = "off"  # We default to "off" on startup.
        # Should the dronetracker-command topic send confirmation that experiment is active?

    def update(self):
        """
        Update the status from the Kafka server
        :return: whether new data was received
        """
        log = self.log.getChild("update")
        msg = self.consumer.poll()  # Update consumer data
        if len(msg):  # is there new data?
            log.debug("Successfully received new status from Kafka server")
            if len(msg) > 1:  # We were sleeping or there were a bunch of things happening
                log.warning("Received multiple packets in one cycle: have we been sleeping?")
            msg = msg[kafka.TopicPartition(self.topic, 0)][-1]  # We need to get the most recent message, thus the -1
            if msg.value not in VALID_STATUS:  # Ensure validity
                log.warning(f"Received invalid status from Kafka server! status={msg.value}. Ignoring message")
                return False
            self.status = msg.value
            return True
        else:
            log.debug("No new data received from poll action.")  # We don't need to do anything, just return.
            # The most recent data is already saved
            return False

    def wait_for_status(self, status: str, hz: int = 10):
        """
        Wait for the server to send a certain status type.
        :param status: the desired status type
        :param hz: the number of times per second to poll (0 = as fast as possible)
        """
        if hz == 0:
            hz = math.inf
        start = time.time()
        log = self.log.getChild("wait_for_status")
        if status not in VALID_STATUS:  # Ensure validity
            raise ValueError(f"Received invalid status from call to wait_for_status()! status={status}")
        while True:
            cycle_start = time.time()
            updated = self.update()
            if updated and self.status == status:  # We are done!
                break
            cycle_end = time.time()
            delta = 1/hz - (cycle_end-cycle_start)
            if delta:
                log.debug(f"Now sleeping for {round(delta, 2)} seconds")
                time.sleep(delta)
        end = time.time()
        log.info(f"Received message of status {status} from Kafka server after {round(start-end, 2)} seconds")


