import asyncio
import os
import sys
sys.path.insert(0, os.path.abspath("."))
from blackboard import Blackboard
from message import MessageBus
from agents.paper_reader_agent import PaperReaderAgent

bb = Blackboard(run_id="smoke_arxiv", topic="transformer attention mechanism")
bus = MessageBus()
agent = PaperReaderAgent(blackboard=bb, bus=bus)
notes = asyncio.run(agent.fetch_arxiv("transformer attention mechanism", limit=3))
print("Notes returned count:", len(notes))
for n in notes:
    print(" - Title:", n.title)
