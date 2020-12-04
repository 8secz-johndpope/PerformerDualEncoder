import os
import warnings
from datetime import time, datetime

import deepspeed
import torch
from transformers import RobertaTokenizer

from modelling_siamese_performer import SiamesePerformer
from preprocessing import Corpus, download_and_extract
from utils import DataLoaderLaper, add_argument, data_collector_deepspeed

warnings.simplefilter(action='ignore', category=FutureWarning)

device = "cuda" if torch.cuda.is_available() else "cpu"

if __name__ == "__main__":

    print("Loading data...")

    assert download_and_extract(path=os.environ.get("DATA_DIR", "./storage"))
    corpus = Corpus()
    corpus.load_corpus(debug=bool(int(os.environ.get("DEBUG", 0))), path=os.environ.get("DATA_DIR", "./storage"))

    tokenizer = RobertaTokenizer.from_pretrained(os.environ.get("PRETRAINED_VOCAB_PATH", "roberta-base"))
    auto_encoder = SiamesePerformer(tokenizer.vocab_size).cuda()

    train_dataset = DataLoaderLaper(
        corpus.get_train() if not bool(int(os.environ.get("DOWNSAMPLE", 0))) else corpus.get_train()[0:1000])

    dev_dataset = DataLoaderLaper(
        corpus.get_dev() if not bool(int(os.environ.get("DOWNSAMPLE", 0))) else corpus.get_train()[0:5000])

    cmd_args = add_argument()
    model_engine, optimizer, trainloader, _ = deepspeed.initialize(args=cmd_args, model=auto_encoder,
                                                                   model_parameters=auto_encoder.parameters(),
                                                                   training_data=train_dataset)

    for epoch in range(int(os.environ.get("EPOCHS", 1))):
        if model_engine.local_rank == 0:
            print(f"{datetime.now()} Epoch {epoch}")

        for i, data in enumerate(trainloader):
            model_engine.train()
            data = data_collector_deepspeed(data, tokenizer, model_engine.local_rank)
            loss = model_engine(**data)
            loss = loss.mean()
            model_engine.backward(loss)
            model_engine.step()
            if model_engine.local_rank != 0:
                continue

            if (i * epoch + i) % int(os.environ.get("STEPS_PER_PRINT")) == 0:
                #batches = [dev_dataset[]]

                print(f"{datetime.now()} Epoch {epoch} iter {i} Loss {loss.item()}")
                model_engine.save_checkpoint(os.environ.get("OUTPUT_DIR"), (i * epoch + i))

    if model_engine.local_rank == 0:
        auto_encoder.fix_projection_matrix()
        auto_encoder.save_pretrained(os.environ.get("OUTPUT_DIR") + "/final_performer.bin")
