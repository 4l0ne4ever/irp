"""Shared queue: Kafka forwarder + job lifecycle -> WebSocket broadcast."""

from queue import Queue

outbound_queue: Queue = Queue()
