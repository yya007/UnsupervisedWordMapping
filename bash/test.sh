#! /bin/bash
git pull
python unsupervised.py --quick_test True --cc_method 'csls_knn_10' --n_epochs 2 --n_iters 2 --map_optimizer "sgd,lr=0.01" --epoch_size 10000 --src_lang en --tgt_lang it --src_emb data/pretrained/en.vec --tgt_emb data/pretrained/it.vec --refinement True
python unsupervised.py --quick_test True  --n_epochs 2 --n_iters 2 --map_optimizer "sgd,lr=0.01" --epoch_size 10000 --src_lang en --tgt_lang it --src_emb data/pretrained/en.vec --tgt_emb data/pretrained/it.vec --refinement True
