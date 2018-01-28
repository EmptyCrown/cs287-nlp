# Text text processing library and methods for pretrained word embeddings
import torchtext
from torchtext.vocab import Vectors, GloVe
import torch
import torch.autograd as autograd
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
import numpy as np

def save_test(model, test):
    "All models should be able to be run with following command."
    upload = []
    # Update: for kaggle the bucket iterator needs to have batch_size 10
    test_iter = torchtext.data.BucketIterator(test, train=False, batch_size=10)
    for batch in test_iter:
        # Your prediction data here (don't cheat!)
        probs = model(batch.text)
        _, argmax = probs.max(1)
        upload += list(argmax.data)

    with open("predictions.txt", "w") as f:
        for u in upload:
            f.write(str(u) + "\n")

def model_eval(model, test):
    test_iter = torchtext.data.BucketIterator(test, train=False, batch_size=10,
                                              device=-1)
    cnt_correct = 0
    cnt_total = 0
    for batch in test_iter:
        probs = model(torch.t(batch.text).contiguous())
        _, argmax = probs.max(1)
        cnt_total += batch.text.size()[1]
        # print(batch.label == argmax, (batch.label == argmax).sum().data[0])
        cnt_correct += (argmax == batch.label).sum().data[0]
    return (cnt_correct, cnt_total)

    