
from Search_Pipeline.engine import SearchEngine
from Search_Pipeline.models import Models
from Search_Pipeline.config import FAISS_INDEX, DOC_IDS_PATH
from Search_Pipeline.evaluation import evaluate

models = Models()
models.load_index(FAISS_INDEX, DOC_IDS_PATH)
engine = SearchEngine(models)

test_cases = [
    {"query": "پردازش تصویر",         "relevant_ids": {90, 62, 84, 27, 79, 55, 38, 57, 89, 51}},
    {"query": "پیشنهاده دکتری 1402", "relevant_ids": {21, 76}},
]
evaluate(engine, test_cases, ce_key=models._ce_key)