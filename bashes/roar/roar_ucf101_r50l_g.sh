#!/bin/bash
CUDA_VISIBLE_DEVICES=0 python model_train/train_ucf101_24_model_roar.py --model r50l --long_range \
--testlist_idx 1 --vis_method g --perturb_ratio 0.0 --num_epochs 40

CUDA_VISIBLE_DEVICES=0 python model_train/train_ucf101_24_model_roar.py --model r50l --long_range \
--testlist_idx 1 --vis_method g --perturb_ratio 0.1 --num_epochs 40

CUDA_VISIBLE_DEVICES=0 python model_train/train_ucf101_24_model_roar.py --model r50l --long_range \
--testlist_idx 1 --vis_method g --perturb_ratio 0.3 --num_epochs 40

CUDA_VISIBLE_DEVICES=0 python model_train/train_ucf101_24_model_roar.py --model r50l --long_range \
--testlist_idx 1 --vis_method g --perturb_ratio 0.5 --num_epochs 40

CUDA_VISIBLE_DEVICES=0 python model_train/train_ucf101_24_model_roar.py --model r50l --long_range \
--testlist_idx 1 --vis_method g --perturb_ratio 0.7 --num_epochs 40

CUDA_VISIBLE_DEVICES=0 python model_train/train_ucf101_24_model_roar.py --model r50l --long_range \
--testlist_idx 1 --vis_method g --perturb_ratio 0.9 --num_epochs 40