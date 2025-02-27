import os
from os.path import join, isdir, isfile

from path_dict import PathDict
path_dict = PathDict()
proj_root = path_dict.proj_root
ds_root = path_dict.ds_root

from utils.ImageShow import *
from utils.ReadingDataset import load_model_and_dataset, getTagScore, loadTags
from process_perturb_res import vis_perturb_res

from visual_meth.integrated_grad import integrated_grad
from visual_meth.blur_integrated_grad import blur_integrated_grad
from visual_meth.gradients import gradients
from visual_meth.perturbation_area import video_perturbation
from visual_meth.grad_cam import grad_cam
from visual_meth.score_cam import score_cam
from visual_meth.smooth_grad import smooth_grad
from visual_meth.excitation_backprop import excitation_bp
from visual_meth.guided_backprop import guided_bp
from visual_meth.linear_approximation import linear_appr
from visual_meth.xrai import xrai

import torch
import torch.multiprocessing as mp
import torch.distributed as dist
from torch.utils.data import Dataset, DataLoader
from torch.nn.parallel import DistributedDataParallel as DDP

import pandas as pd
from tqdm import tqdm
import math
import time
import csv
import copy

def main_worker(gpu, args):
    if args.vis_method == 'perturb':
        if args.model == 'v16l':
            step = 14
            sigma = 23
        else:
            step = 7
            sigma = 11
    batch_size = args.batch_size

    rank = gpu	                          
    dist.init_process_group(                                   
    	backend='nccl',                                         
   		init_method='env://',                                   
    	world_size=args.world_size,                              
    	rank=rank                                               
    )  

    torch.manual_seed(0)

    model_ft, video_datasets = load_model_and_dataset(args.dataset, args.model, args.phase_set)
    model_ft = model_ft.eval()  # important!
    model_ft.cuda(gpu)
    model_ft = DDP(model_ft, device_ids=[gpu])
    # print(model_ft)

    # Initialize the dataset and dataloader
    samplers = {x: torch.utils.data.distributed.DistributedSampler(video_datasets[x], 
                        num_replicas=args.world_size, rank=rank) for x in args.phase_set}
    dataloaders = {x: DataLoader(video_datasets[x], batch_size=batch_size, shuffle=False, 
                        num_workers=0, sampler=samplers[x], pin_memory=False) for x in args.phase_set}
    print(rank, {x: 'Num of batches:{}'.format(len(dataloaders[x])) for x in args.phase_set})

    if args.visualize:
        plot_save_path = f"{proj_root}/visual_res/{args.save_label}"
        os.makedirs(plot_save_path, exist_ok=True)

    # res_buf = {'train': [], 'val': []}
    for phase in args.phase_set:
        res_buf = {'train': [], 'val': []}
        for samples in dataloaders[phase]:
            # x: 1x3x16x112x112; label: 1; output mask: 
            # 1x1x16x112x112; fidx_tensors: 1x16;
            x, labels, seg_names, fidx_tensors = samples[:4]
            x = x.cuda(gpu)
            labels = labels.to(dtype=torch.long).cuda(gpu)

            if args.dataset == 'sthsthv2':
                action_label = samples[4]

            y = model_ft(x)
            lowest_probs, lowest_labels = torch.min(y, dim=1)

            device = x.device
            print(seg_names)

            if args.vis_method in ['g', 'ig', 'blur_ig']:
                if args.vis_method == 'g':
                    res = gradients(x, labels, model_ft, device, multiply_input=False, polarity='both')
                elif args.vis_method == 'ig':
                    res = integrated_grad(x, labels, model_ft, device, steps=25, polarity='both')
                elif args.vis_method == 'blur_ig':
                    res = blur_integrated_grad(x, labels, model_ft, device, steps=25, polarity='both')
                heatmaps_np = res.numpy()   # Nx1xTxHxW
            elif args.vis_method in ['sg', 'sg2', 'sg_var']:
                variant_dict = {'sg': None, 'sg2': 'square', 'sg_var': 'variance'}
                variant = variant_dict[args.vis_method]
                res = smooth_grad(x, labels, model_ft, device, nsamples=25, variant=variant)
                heatmaps_np = res.numpy()   # Nx1xTxHxW
            elif args.vis_method in ['grad_cam', 'eb', 'score_cam']:
                if args.model == 'r2p1d':
                    layer_name = ['layer4']
                    # layer_name = ['layer3']
                elif args.model == 'v16l':
                    layer_name = ['pool5']
                elif args.model == 'r50l':
                    layer_name = ['6']
                elif args.model == 'tsm':
                    layer_name = ['layer4']
                if args.vis_method == 'grad_cam':
                    res = grad_cam(x, labels, model_ft, args.model, device, layer_name=layer_name, norm_vis=True)
                elif args.vis_method == 'eb':
                    res = excitation_bp(x, labels, model_ft, args.model, device, layer_name=layer_name, norm_vis=True)
                elif args.vis_method == 'score_cam':
                    res = score_cam(x, labels, model_ft, args.model, device, layer_name=layer_name, norm_vis=True)
                heatmaps_np = res.numpy()   # Nx1xTxHxW
            elif args.vis_method == 'gbp':
                res = guided_bp(x, labels, model_ft)
                heatmaps_np = res.numpy()
            elif args.vis_method == 'la':
                res = linear_appr(x, labels, model_ft)
                heatmaps_np = res.numpy()
            elif args.vis_method == 'xrai':
                res = xrai(x, labels, model_ft, device)
                heatmaps_np = res.numpy()
            elif args.vis_method == 'perturb':
                sigma = 11 if x.shape[-1] == 112 else 23
                if args.lowest_label:
                    res = video_perturbation(
                        model_ft, x, lowest_labels, areas=args.areas, sigma=sigma, 
                        max_iter=args.perturb_niter, variant="preserve",
                        gpu_id=gpu, print_iter=200, perturb_type=args.perturb_type,
                        with_core=args.perturb_withcore, 
                        core_num_keyframe=args.perturb_num_keyframe,
                        core_spatial_size=args.perturb_spatial_size,
                        core_shape=args.perturb_core_shape)[0]
                else:
                    res = video_perturbation(
                            model_ft, x, labels, areas=args.areas, sigma=sigma, 
                            max_iter=args.perturb_niter, variant="preserve",
                            gpu_id=gpu, print_iter=200, perturb_type=args.perturb_type,
                            with_core=args.perturb_withcore, 
                            core_num_keyframe=args.perturb_num_keyframe,
                            core_spatial_size=args.perturb_spatial_size,
                            core_shape=args.perturb_core_shape)[0]
                # print(res.shape)
                heatmaps_np = res.numpy()   # NxAx1xTxHxW
                # print(heatmaps_np.shape)
                
            for bidx in range(len(seg_names)):
                seg_name = copy.deepcopy(seg_names[bidx].split("/")[-1])
                heatmap = heatmaps_np[bidx].astype('float16')
                fidxs = copy.deepcopy(fidx_tensors[bidx].detach().cpu().numpy())
                fidxs = fidxs.astype('uint16')

                res_buf[phase].append({"video_name": seg_name, "mask": heatmap, "fidx": fidxs}) 

                if args.visualize:
                    inp_np = voxel_tensor_to_np(x[bidx].detach().cpu())   # 3 x num_f x 224 224
                    plot_save_name = seg_name + '.jpg'
                    if args.dataset == 'sthsthv2':
                        plot_save_name = plot_save_name.replace('.jpg', f'_{action_label[bidx]}.jpg')
                    print(plot_save_name)

                    if args.vis_method == 'perturb':
                        merged_fig, _ = vis_perturb_res(args.dataset, args.model, seg_name, 
                                                        heatmaps_np[bidx], frame_index=fidxs, white_bg=False)
                        Image.fromarray(merged_fig).save(os.path.join(args.plot_save_path, plot_save_name))
                    else:
                        if args.vis_method == 'grad_cam' or args.vis_method == 'eb' or args.vis_method == 'score_cam':
                            heatmap_np = overlap_maps_on_voxel_np(inp_np, heatmaps_np[bidx,0])
                        else:
                            heatmap_np = heatmaps_np[bidx].repeat(3, axis=0)      # 3 x num_f x 224 224
                        plot_voxel_np(inp_np, heatmap_np, title=seg_name, 
                                        save_path=os.path.join(args.plot_save_path, plot_save_name) )

        res_save_name = f'{args.save_label}_gpu{gpu}_{phase}.pt'
        torch.save(res_buf, join(args.res_save_path, res_save_name))
        print(f'GPU:{gpu}, Phase:{phase} saved.', res_save_name)
    # res_save_name = f'{args.save_label}_gpu{gpu}.pt'
    # torch.save(res_buf, join(args.res_save_path, res_save_name))
    # print(f'GPU:{gpu} saved', res_save_name)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    # parser.add_argument("--testlist_idx", type=int, default=2, choices=[1, 2])
    # parser.add_argument("--num_f", type=int, default=16, choices=[8, 16])
    # parser.add_argument("--long_range", action='store_true')
    parser.add_argument("--dataset", type=str, choices=['epic', 'ucf101', 'cat_ucf', 'sthsthv2'])
    parser.add_argument("--model", type=str, choices=['r2p1d', 'v16l', 'r50l', 'tsm'])
    parser.add_argument("--vis_method", type=str, 
                        choices=['g', 'ig', 'sg', 'sg2', 'grad_cam', 'perturb', 'eb', 
                                 'gbp', 'la', 'blur_ig', 'score_cam', 'xrai'])
    parser.add_argument("--only_test", action="store_true")
    parser.add_argument("--only_train", action="store_true")
    parser.add_argument("--num_gpu", type=int, default=-1)
    parser.add_argument("--visualize", action='store_true')
    parser.add_argument("--extra_label", type=str, default="")
    parser.add_argument("--retrain_type", type=str, default="full", choices=["full", "half"])
    parser.add_argument("--lowest_label", action='store_true')
    parser.add_argument("--batch_size", type=int, default=8)

    parser.add_argument("--perturb_niter", type=int, default=1000)
    parser.add_argument("--perturb_withcore", action='store_true')
    parser.add_argument("--perturb_type", type=str, default='blur')
    parser.add_argument("--perturb_num_keyframe", type=int, default=8)
    parser.add_argument("--perturb_core_shape", type=str, default='ellipsoid', choices=["ellipsoid", "cylinder"])
    parser.add_argument("--perturb_spatial_size", type=int, default=11)

    parser.add_argument("--master_addr", type=str, default="127.0.1.1")
    parser.add_argument("--master_port", type=str, default="29501")

    args = parser.parse_args()

    assert args.only_test & args.only_train == False, "only_test and only_train cannot be true together!"
    # args.phase_set = ["val"] if args.only_test else ["val", "train"]
    # args.phase_set = ["train"] if args.only_train else ["val", "train"]
    args.phase_set = ["val", "train"]
    if args.only_test:
        args.phase_set = ["val"]
    if args.only_train:
        args.phase_set = ["train"]

    if args.dataset == 'cat_ucf':
        args.phase_set = ["val"]

    print(args.phase_set)

    # Set path to save masks generated by perturbations
    save_label = f"{args.dataset}_{args.model}_{args.vis_method}_{args.retrain_type}"
    if args.lowest_label:
        save_label = save_label + "_lowest"
    if args.perturb_withcore:
        save_label = save_label + "_core" + f"{args.perturb_num_keyframe}"
    if args.perturb_type == 'fade':
        save_label = save_label + "_fade"
    if args.perturb_core_shape == 'cylinder':
        save_label = save_label + "_cylinder"
    if args.extra_label != "":
        save_label = save_label + f"_{args.extra_label}"
    args.save_label = save_label
    print(save_label)

    res_save_path = f"{proj_root}/exe_res"
    os.makedirs(res_save_path, exist_ok=True)
    args.res_save_path = res_save_path

    if args.visualize:
        plot_save_path = f"{proj_root}/visual_res/{save_label}"
        os.makedirs(plot_save_path, exist_ok=True)
        args.plot_save_path = plot_save_path

    if args.vis_method == 'perturb':
        args.areas = [0.05, 0.1, 0.15, 0.5]
        if args.dataset == 'cat_ucf':
            args.areas = [0.02, 0.05, 0.1]
        if args.dataset == 'sthsthv2' and args.model == 'tsm':
            args.areas = [0.05, 0.1, 0.15, 0.3]

    multi_gpu = True
    if args.num_gpu == -1:
        num_devices = torch.cuda.device_count()
    else:
        num_devices = args.num_gpu
        assert num_devices <= torch.cuda.device_count() and num_devices >= 1, \
            f"Set number of GPUs: {args.num_gpu}, but only have {torch.cuda.device_count()} GPUs."
    args.world_size = num_devices
    # os.environ['MASTER_ADDR'] = '127.0.1.2'
    # os.environ['MASTER_PORT'] = '29502' 
    os.environ['MASTER_ADDR'] = args.master_addr
    os.environ['MASTER_PORT'] = args.master_port

    print(f'Use {num_devices} GPUs.')
    mp.spawn(main_worker, nprocs=num_devices, args=(args,))
    print('*** This is the end of the multiprocessing ***')

    all_res = {'train': [], 'val': []}
    for phase in args.phase_set:
        for device_id in range(num_devices):
            res_save_name = f'{args.save_label}_gpu{device_id}_{phase}.pt'
            res_buf = torch.load(join(args.res_save_path, res_save_name))
            all_res[phase] += res_buf[phase]
    phase_label = ""
    if args.only_test:
        phase_label = "_test"
    if args.only_train:
        phase_label = "_train"
    res_save_name = f'{args.save_label}{phase_label}.pt'
    torch.save(all_res, join(args.res_save_path, res_save_name))
    print(f'Saved all samples as {res_save_name}.')

    for phase in args.phase_set:
        for device_id in range(num_devices):
            res_save_name = f'{args.save_label}_gpu{device_id}_{phase}.pt'
            os.remove(join(args.res_save_path, res_save_name))
    print(f'Deleted all samples saved by each GPU.')
