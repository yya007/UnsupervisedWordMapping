#! /bin/bash
#SBATCH --account=p_masi_gpu
#SBATCH --partition=pascal
#SBATCH --gres=gpu:1
#SBATCH --nodes=1
#SBATCH --ntasks=2
#SBATCH --mem=40G
#SBATCH --time=120:00:00
#SBATCH --output=/scratch/yaoy4/UnsupervisedWordMapping/log/run2.log
module load Anaconda2
source activate FCN
cd /scratch/yaoy4/UnsupervisedWordMapping/
python unsupervised.py --lambda_a 20 --lambda_b 20 --n_epochs 30 --src_lang en --tgt_lang it --src_emb data/pretrained/en.vec --tgt_emb data/pretrained/it.vec --refinement True
python unsupervised.py --lambda_a 100 --lambda_b 100 --n_epochs 30 --src_lang en --tgt_lang it --src_emb data/pretrained/en.vec --tgt_emb data/pretrained/it.vec --refinement True
