#!/bin/bash

#$ -N sthsthv2_r50l
#$ -l rt_F=1
#$ -l h_rt=24:00:00
#$ -o outs_sthsthv2/r50l_perturb_proc.txt
#$ -j y
#$ -cwd
source /etc/profile.d/modules.sh

source ${HOME}/.bashrc
conda activate pytorch1.1

python run_all.py --dataset sthsthv2 --model r50l --only_test --vis_method perturb \
--perturb_niter 1200 --batch_size 4

python process_perturb_res.py --dataset sthsthv2 --model r50l --vis_method perturb \
--only_test
# python run_all.py --dataset sthsthv2 --model r50l --only_test --vis_method perturb \
# --perturb_niter 1200 --perturb_withcore --perturb_num_keyframe 8 --batch_size 4

# python run_all.py --dataset sthsthv2 --model r50l --only_test --vis_method perturb \
# --perturb_niter 1200 --perturb_withcore --perturb_num_keyframe 14 --batch_size 4


