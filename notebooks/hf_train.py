# -*- coding: utf-8 -*-
"""hf_Train.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1Hz0mqj9M4CB18dQn_Ind6iv4nMsXisxl
"""

!pip install transformers datasets nlpaug
import nltk
nltk.download('averaged_perceptron_tagger')
nltk.download('wordnet')

import pandas as pd 
from google.colab import drive
import nlpaug
import nlpaug.augmenter.word as naw
import random 

drive.mount('/content/drive/')
pth = '/content/drive/MyDrive/msci-598-nl-project/fnc-1/'

def load_and_join(headlines, bodies): 
    train_bodies = pd.read_csv(bodies).set_index('Body ID')
    train_headlines = pd.read_csv(headlines).set_index('Body ID')
    return train_headlines, train_bodies

pth_to_bodies = pth + 'competition_test_bodies.csv'
pth_to_headlines = pth + 'competition_test_stances.csv'
test_headlines, test_bodies = load_and_join(pth_to_headlines, pth_to_bodies)
test = test_headlines.join(test_bodies)
test['target_stage1'] = 'None'
test['labels'] = test.Stance
test.loc[test.Stance == 'unrelated', 'target_stage1'] = 0 #'unrelated'
test.loc[test.Stance != 'unrelated', 'target_stage1'] = 1 #'related'
test.loc[test.Stance == 'agree', 'labels'] = 0 #'agree'
test.loc[test.Stance == 'disagree', 'labels'] = 1 #'disagee'
test.loc[test.Stance == 'discuss', 'labels'] = 2 #'discuss'
test.loc[test.Stance == 'unrelated', 'labels'] = None
test.drop(['Stance'], inplace=True,axis=1)

aug = naw.SynonymAug(aug_src='wordnet',aug_max=5)
n_s = 2

def augment(headline, articleBody):
  p = random.uniform(0, 1)
  if p < 0.2: # augment headline
    new_text = aug.augment(headline,n=n_s)
    s = pd.DataFrame( columns = ['Headline','articleBody'])
    s['Headline'] = new_text 
    s['articleBody'] = [articleBody]*n_s
    return s
  else: #augment body
    new_text =  aug.augment(articleBody,n=n_s)
    s = pd.DataFrame( columns = ['Headline','articleBody'])
    s['Headline'] = [headline]*n_s
    s['articleBody'] = new_text
    return s

cols = ['Headline', 'articleBody', 'summarized_articles', 'labels']
df = pd.read_csv(pth+"withSumTrain.csv")
df = df.loc[~df.labels.isna()][cols]
df_disagree = df.loc[df.labels == 1]
new_disagree_pts = df_disagree.apply(lambda x: augment(x.Headline,x.articleBody), axis=1)
new_disagree_pts = pd.concat([x for x in new_disagree_pts],axis=0)
new_disagree_pts['labels'] = 1 
new_disagree_pts.reset_index(inplace = True)

from datasets import Dataset,DatasetDict

test = pd.read_csv(pth+"withSumTest.csv")
test = test.loc[~test.labels.isna()][cols]
df.labels = df.labels.astype(int)
test.labels = test.labels.astype(int)
min_sz = 4000 #df.labels.value_counts().min()
df_agree = df.loc[df.labels == 0] #.sample(min_sz)
df_discuss = df.loc[df.labels == 2]#.sample(min_sz)
df_disagree = df.loc[df.labels == 1] #.sample(min_sz)
df = pd.concat([df_agree,df_discuss,df_disagree],axis=0) #.sample(min_sz*3)
df = pd.concat([df,new_disagree_pts],axis=0)
df.reset_index(inplace=True,drop=True)
train = Dataset.from_pandas(df.sample(len(df)))
test = Dataset.from_pandas( test)
# 90% train, 10% test + validation
train_testvalid = train.train_test_split(0.2)
# Split the 10% test + valid in half test, half valid
test_valid = train_testvalid['test']
# gather everyone if you want to have a single DatasetDict
train_test_valid_dataset = DatasetDict({
    'train': train_testvalid['train'],
    'test': test,
    'valid':test_valid})

label_mapper = {2: "discuss", 1: "disagree", 0:"agree"}

df.labels.value_counts()

from transformers import AutoTokenizer, AutoModelForSequenceClassification, DataCollatorWithPadding, Trainer

checkpoint = "roberta-base"
tokenizer = AutoTokenizer.from_pretrained(checkpoint)

def tokenize_function(example):
    return tokenizer(example["Headline"], example["articleBody"], padding=True, truncation=True)

tokenized_train_test_valid_dataset = train_test_valid_dataset.map(tokenize_function, batched=True)

model = None
import gc
gc.collect()

data_collator = DataCollatorWithPadding(tokenizer=tokenizer)
model = AutoModelForSequenceClassification.from_pretrained(checkpoint, num_labels=3)

from transformers import TrainingArguments

training_args = TrainingArguments("test-trainer",  
                                  evaluation_strategy="epoch", 
                                  per_device_train_batch_size=16, 
                                  num_train_epochs=5,              # total number of training epochs
                                  weight_decay=0.4,               # strength of weight decay
                                  per_device_eval_batch_size=16)

from datasets import load_metric
import numpy as np 

def compute_metrics(eval_preds):
    metric = load_metric("matthews_correlation", "accuracy")
    logits, labels = eval_preds
    predictions = np.argmax(logits, axis=-1)
    return metric.compute(predictions=predictions, references=labels)

trainer = Trainer(
    model,
    training_args,
    train_dataset=tokenized_train_test_valid_dataset["train"],
    eval_dataset=tokenized_train_test_valid_dataset["valid"],
    data_collator=data_collator,
    tokenizer=tokenizer,
    compute_metrics=compute_metrics,

)

trainer.train()

trainer.save_model(pth + 'stance_detector_stage2_roberta_best')

preds = trainer.predict(tokenized_train_test_valid_dataset['test'])

! pip install -q scikit-plot

import scikitplot as skplt

skplt.metrics.plot_confusion_matrix(
    tokenized_train_test_valid_dataset['test']['labels'], 
    preds[0].argmax(axis=1), 
    figsize=(12,12))

from sklearn.metrics import classification_report
print(classification_report(tokenized_train_test_valid_dataset['test']['labels'], preds[0].argmax(axis=1), target_names=['agree','disagree','discuss']))

"""# Final Pipeline:

Define an inference function combining Jaccard w/ Roberta
"""

!pip install transformers datasets

from transformers import AutoTokenizer, AutoModelForSequenceClassification, DataCollatorWithPadding, Trainer
from datasets import Dataset
import pandas as pd 
from google.colab import drive

drive.mount('/content/drive/')
pth = '/content/drive/MyDrive/msci-598-nl-project/fnc-1/'

checkpoint = "roberta-base"
tokenizer = AutoTokenizer.from_pretrained(checkpoint)

def tokenize_function(example):
    return tokenizer(example["Headline"], example["articleBody"], padding=True, truncation=True)

test_related.target_stage1.value_counts(),test.target_stage1.value_counts()

test = pd.read_csv(pth + 'stg1_test_results_opt.csv')
test_related = test.loc[(test.pred == "related")]
test_df = Dataset.from_pandas( test_related)
test_tok = test_df.map(tokenize_function, batched=True)

model_path = pth + 'stance_detector_stage2_roberta_best'
model = AutoModelForSequenceClassification.from_pretrained(model_path, num_labels=3) 
# Define test trainer
test_trainer = Trainer(model) 
# Make prediction
raw_pred, _, _ = test_trainer.predict(test_tok)

import numpy as np

# Preprocess raw predictions
label_mapper = {2: "discuss", 1: "disagree", 0:"agree"}
y_pred = np.argmax(raw_pred, axis=1)
y_pred2=pd.Series(y_pred, index =test_related.index ).map(label_mapper)

final_test = pd.concat([test.drop(test_related.index), test_related.join(y_pred2.rename('stg2_preds'))])

final_test.stg2_preds.fillna(final_test.target_stage1).unique()

final_test['all_pred'] = final_test['stg2_preds']
final_test['all_pred'].fillna("unrelated",inplace=True)

final_test[['Stance','pred','stg2_preds','all_pred']].loc[(final_test.Stance == 'unrelated') & (final_test.pred =='related')]

final_test

final_test.to_csv(pth+"all_pred.csv",index=False)

from sklearn.metrics import classification_report

print(classification_report(final_test.Stance, 
                            final_test.all_pred))

LABELS = ['agree', 'disagree', 'discuss', 'unrelated']
LABELS_RELATED = ['unrelated','related']
RELATED = LABELS[0:3]

def score_submission(gold_labels, test_labels):
    score = 0.0
    cm = [[0, 0, 0, 0],
          [0, 0, 0, 0],
          [0, 0, 0, 0],
          [0, 0, 0, 0]]

    for i, (g, t) in enumerate(zip(gold_labels, test_labels)):
        g_stance, t_stance = g, t
        if g_stance == t_stance:
            score += 0.25
            if g_stance != 'unrelated':
                score += 0.50
        if g_stance in RELATED and t_stance in RELATED:
            score += 0.25

        cm[LABELS.index(g_stance)][LABELS.index(t_stance)] += 1

    return score, cm


def print_confusion_matrix(cm):
    lines = []
    header = "|{:^11}|{:^11}|{:^11}|{:^11}|{:^11}|".format('', *LABELS)
    line_len = len(header)
    lines.append("-"*line_len)
    lines.append(header)
    lines.append("-"*line_len)

    hit = 0
    total = 0
    for i, row in enumerate(cm):
        hit += row[i]
        total += sum(row)
        lines.append("|{:^11}|{:^11}|{:^11}|{:^11}|{:^11}|".format(LABELS[i],
                                                                   *row))
        lines.append("-"*line_len)
    print('\n'.join(lines))


def report_score(actual,predicted):
    score,cm = score_submission(actual,predicted)
    best_score, _ = score_submission(actual,actual)

    print_confusion_matrix(cm)
    print("Score: " +str(score) + " out of " + str(best_score) + "\t("+str(score*100/best_score) + "%)")
    return score*100/best_score


if __name__ == "__main__":
    actual = [0,0,0,0,1,1,0,3,3]
    predicted = [0,0,0,0,1,1,2,3,3]
    report_score([x for x in final_test.Stance.tolist()],[x for x in final_test.all_pred.tolist()])

final_test.Stance.value_counts()

