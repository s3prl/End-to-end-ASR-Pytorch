#!/usr/bin/env python
# coding: utf-8
import os
import yaml
import torch
import argparse
import numpy as np
from torch.distributed import get_rank, get_world_size

# For reproducibility, comment these may speed up training
torch.backends.cudnn.deterministic = True
torch.backends.cudnn.benchmark = False

# Arguments
parser = argparse.ArgumentParser(description='Training E2E asr.')
parser.add_argument('--config', type=str, help='Path to experiment config.')
parser.add_argument('--name', default=None, type=str, help='Name for logging.')
parser.add_argument('--logdir', default='log/', type=str,
                    help='Logging path.', required=False)
parser.add_argument('--ckpdir', default='ckpt/', type=str,
                    help='Checkpoint path.', required=False)
parser.add_argument('--outdir', default='result/', type=str,
                    help='Decode output path.', required=False)
parser.add_argument('--load', default=None, type=str,
                    help='Load pre-trained model (for training only)', required=False)
parser.add_argument('--seed', default=0, type=int,
                    help='Random seed for reproducable results.', required=False)
parser.add_argument('--cudnn-ctc', action='store_true',
                    help='Switches CTC backend from torch to cudnn')
parser.add_argument('--njobs', default=6, type=int,
                    help='Number of threads for dataloader/decoding.', required=False)
parser.add_argument('--cpu', action='store_true', help='Disable GPU training.')
parser.add_argument('--no-pin', action='store_true',
                    help='Disable pin-memory for dataloader')
parser.add_argument('--test', action='store_true', help='Test the model.')
parser.add_argument('--no-msg', action='store_true', help='Hide all messages.')
parser.add_argument('--lm', action='store_true',
                    help='Option for training RNNLM.')
# Following features in development.
parser.add_argument('--amp', action='store_true', help='Option to enable AMP.')
parser.add_argument('--reserve-gpu', default=0, type=float,
                    help='Option to reserve GPU ram for training.')
parser.add_argument('--jit', action='store_true',
                    help='Option for enabling jit in pytorch. (feature in development)')
parser.add_argument('--upstream',
                    help='Specify the upstream variant according to torch.hub.list')
parser.add_argument('--upstream_feature_selection',
                    help=f'Specify the layer to be extracted as the representation according to torch.hub.help')
parser.add_argument('--upstream_refresh', action='store_true',
                    help='Re-download cached ckpts for on-the-fly upstream variants')
parser.add_argument('--upstream_ckpt', metavar='{PATH,URL,GOOGLE_DRIVE_ID}',
                    help='Only set when the specified upstream has \'ckpt\' as an argument in torch.hub.help')
parser.add_argument('--upstream_trainable', '-f', action='store_true',
                    help='To fine-tune the whole upstream model')
parser.add_argument('--upstream_same_stride', action='store_true',
                    help='Make sure all upstream features are projected to the same stride in waveform seconds.')
parser.add_argument('--cache_dir', help='Explicitly set the dir for torch.hub')
parser.add_argument('--local_rank', type=int,
                    help=f'The GPU id this process should use while distributed training. \
                           None when not launched by torch.distributed.launch')
parser.add_argument('--backend', default='nccl', help='The backend for distributed training')
parser.add_argument('--load_ddp_to_nonddp', action='store_true',
                    help='The checkpoint is trained with ddp but loaded to a non-ddp model')
parser.add_argument('--load_nonddp_to_ddp', action='store_true',
                    help='The checkpoint is trained without ddp but loaded to a ddp model')
parser.add_argument('--dryrun', action='store_true',
                    help='Iterate the dataset decendingly by sequence length to make sure the training will not OOM')
parser.add_argument('--reinit_optimizer', action='store_true',
                    help='Load model without loading optimizer')

###
paras = parser.parse_args()
setattr(paras, 'gpu', not paras.cpu)
setattr(paras, 'pin_memory', not paras.no_pin)
setattr(paras, 'verbose', not paras.no_msg)
config = yaml.load(open(paras.config, 'r'), Loader=yaml.FullLoader)

if paras.cache_dir is not None:
    os.makedirs(paras.cache_dir, exist_ok=True)
    torch.hub.set_dir(paras.cache_dir)

# When torch.distributed.launch is used
if paras.local_rank is not None:
    torch.cuda.set_device(paras.local_rank)
    torch.distributed.init_process_group(paras.backend)

np.random.seed(paras.seed)
torch.manual_seed(paras.seed)
if torch.cuda.is_available():
    torch.cuda.manual_seed_all(paras.seed)

# Hack to preserve GPU ram just incase OOM later on server
if paras.gpu and paras.reserve_gpu > 0:
    buff = torch.randn(int(paras.reserve_gpu*1e9//4)).cuda()
    del buff

if paras.lm:
    # Train RNNLM
    from bin.train_lm import Solver
    mode = 'train'
else:
    if paras.test:
        # Test ASR
        assert paras.load is None, 'Load option is mutually exclusive to --test'
        from bin.test_asr import Solver
        mode = 'test'
    else:
        # Train ASR
        from bin.train_asr import Solver
        mode = 'train'


solver = Solver(config, paras, mode)
solver.load_data()
solver.set_model()
solver.exec()
