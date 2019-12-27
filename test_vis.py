'''
@Author: ConghaoWong
@Date: 2019-12-25 19:15:53
@LastEditors  : ConghaoWong
@LastEditTime : 2019-12-27 09:39:05
@Description: Visualization UI for prediction
'''

import argparse
import os
import time
from tkinter import *

import cv2
import numpy as np
import tensorflow as tf
from PIL import Image, ImageTk

from models import LSTM_ED
from PrepareTrainData import prepare_agent_for_test
from helpmethods import (
    dir_check,
    predict_linear_for_person,
)

TIME = time.strftime('%Y%m%d-%H%M%S',time.localtime(time.time()))

coe = 0
coe_list = [
    '?',
    [[]],
    [[15.481, 0, 720], [12.386, 0, 576]],
]

class Visualization():
    def __init__(self, background_image_path, args):
        self.root = Tk()
        self.root.title('Project Erina')
        self.inputs_list = []
        self.args = args
        self.obs_frames = args.obs_frames
        self.pred_frames = args.pred_frames

        self.clickcount = 0
        self.first_x = 0
        self.first_y = 0
        self.reduce_coe = 2

        self.predcition_initialize(args)
        background_image = cv2.imread(background_image_path)
        image_shape = background_image.shape

        self.canvas = Canvas(self.root, width=image_shape[1], height=image_shape[0])
        self.canvas.bind('<Button-1>', self.click_callback)
        self.show_background_image(background_image_path)
        
        self.canvas.pack()

        self.reset_buttom = Button(self.root, text="clear", command=self.reset)
        self.reset_buttom.pack(fill="both", expand=True, padx=5, pady=3)

        self.prediction_buttom = Button(self.root, text="Prediction!", command=self.prediction)
        self.prediction_buttom.pack(fill="both", expand=True, padx=5, pady=3)

        self.test_buttom = Button(self.root, text="test", command=self.print_list)
        self.test_buttom.pack(fill="both", expand=True, padx=5, pady=3)

        self.text_box = Text(height=1)
        self.text_box.pack(expand=True, padx=5, pady=3)

        self.realtime_switch_var = IntVar()
        self.realtime_switch = Checkbutton(self.root, text="Real Time Prediction", variable=self.realtime_switch_var)
        self.realtime_switch.pack(expand=True, padx=5, pady=3)

        self.root.mainloop()
        cv2.destroyAllWindows()

    def predcition_initialize(self, args):
        self.pred_model = LSTM_ED(0, args)
        self.pred_model.run_commands()

    def show_background_image(self, background_image_path):
        image = Image.open(background_image_path)  
        self.image_tk = ImageTk.PhotoImage(image) 
        self.canvas.create_image(0, 0, anchor=NW, image=self.image_tk)
    
    def reset(self):
        self.inputs_list = []
        self.canvas.delete('inputs')
        self.text_box.delete('1.0', 'end')
    
    def click_callback(self, event):
        x, y = [event.x, event.y]
        self.canvas.create_rectangle(x-4, y-4, x+4,
                                y+4, fill='white', outline='blue', width=3, tags='inputs')

        self.inputs_list.append(np.stack(pixel2real(x, y)))
        if len(self.inputs_list) > self.obs_frames:
            self.inputs_list.pop(0)

        if self.realtime_switch_var.get():
            self.prediction()

    def prediction(self):
        if len(self.inputs_list) < self.obs_frames:
            return
        
        self.text_box.delete('1.0', 'end')
        traj_current = np.reshape(np.stack(self.inputs_list), [1, self.obs_frames, 2]).astype(np.float32)
        pred_k_list = np.stack([traj.numpy() for traj in self.pred_model.model(traj_current)[0]])

        for result in pred_k_list:
            for point in result:
                x, y = real2pixel(point[0], point[1])
                self.canvas.create_rectangle(
                    x-4, y-4, x+4, y+4, 
                    fill='green', 
                    outline='green', 
                    width=3, 
                    tags='inputs'
                )

            score = smooth_loss(traj_current[0], result)
            for score_one in score:
                self.text_box.insert('end', '{:.2f},'.format(score_one))
            
            if score.min() <= 0.6:
                self.text_box.insert('end', '结果不可靠，开始尝试线性预测！')
                linear_result = predict_linear_for_person(
                    traj_current[0], 
                    self.pred_frames+self.obs_frames, 
                    different_weights=0.95
                )[self.obs_frames:]

                for point in linear_result:
                    x, y = real2pixel(point[0], point[1])
                    self.canvas.create_rectangle(
                        x-4, y-4, x+4, y+4, 
                        fill='red', 
                        outline='red', 
                        width=3, 
                        tags='inputs'
                    )

        
    def print_list(self):
        print(self.inputs_list)
        print(self.realtime_switch_var.get())


def smooth_loss(obs, pred, step=2, return_min=False):
    start_point = obs[-step:]
    pred_frames = len(pred)
    score_list = []

    delta = np.zeros_like(pred)
    for frame in range(step, pred_frames):
        delta[frame] = pred[frame] - pred[frame-step]
    
    for frame in range(step):
        delta[frame] = pred[frame] - start_point[frame]

    cosine_list = [calculate_cosine(delta[frame-1], delta[frame]) for frame in range(1, pred_frames)]

    if return_min:
        return np.stack(cosine_list).min()
    else:
        return np.stack(cosine_list)


def calculate_cosine(p1, p2, absolute=True):
    l_p1 = np.linalg.norm(p1)
    l_p2 = np.linalg.norm(p2)
    dot = np.sum(p1 * p2)
    result = dot/(l_p1 * l_p2)
    if absolute:
        result = np.abs(result)
    return result


def pixel2real(x, y):
    xr = coe[0][1] + (coe[0][0] - coe[0][1]) * (x/coe[0][2])
    yr = coe[1][1] + (coe[1][0] - coe[1][1]) * (1 - y/coe[1][2])
    return [yr, xr]


def real2pixel(x, y):
    xp = coe[0][2] * (1 - (x - coe[0][1]) / (coe[0][0] - coe[0][1]))  - 140
    yp = coe[1][2] * ((y - coe[1][1]) / (coe[1][0] - coe[1][1]))
    return [int(yp), int(xp)]


def get_parser():
    parser = argparse.ArgumentParser(description='linear')

    # basic settings
    parser.add_argument('--obs_frames', type=int, default=8)
    parser.add_argument('--pred_frames', type=int, default=12)
    parser.add_argument('--test_set', type=int, default=2)
    parser.add_argument('--gpu', type=int, default=1)

    # test settings
    parser.add_argument('--test', type=int, default=False)
   
    # save/load settings
    parser.add_argument('--model_name', type=str, default='model')
    parser.add_argument('--save_model', type=int, default=True)
    parser.add_argument('--load', type=str, default='DO NOT USE')
    parser.add_argument('--draw_results', type=int, default=True)
    parser.add_argument('--save_base_dir', type=str, default='./logs')
    parser.add_argument('--log_dir', type=str, default='DO_NOT_CHANGE')
    parser.add_argument('--save_per_step', type=bool, default=True)

    # LSTM args
    parser.add_argument('--model', type=str, default='LSTM-ED')
    parser.add_argument('--k', type=int, default=15)
    parser.add_argument('--save_k_results', type=bool, default=False)
    return parser


def gpu_config(args):
    os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID" 
    os.environ["CUDA_VISIBLE_DEVICES"] = str(args.gpu)
    gpus = tf.config.experimental.list_physical_devices(device_type='GPU')
    for gpu in gpus:
        tf.config.experimental.set_memory_growth(gpu, True)


def main():
    global coe
    args = get_parser().parse_args()
    log_dir_current = TIME + args.model_name + args.model + str(args.test_set)
    args.log_dir = os.path.join(dir_check(args.save_base_dir), log_dir_current)
    coe = coe_list[args.test_set]
    gpu_config(args)

    load_list = [
        './logs/20191224-22185212000e-10NR-ED-LSTM-ED0/12000e-10NR-ED-',
        './logs/20191224-22185912000e-10NR-ED-LSTM-ED1/12000e-10NR-ED-',
        './logs/20191224-22190512000e-10NR-ED-LSTM-ED2/12000e-10NR-ED-',
        './logs/20191224-22191112000e-10NR-ED-LSTM-ED3/12000e-10NR-ED-',
        './logs/20191224-22191912000e-10NR-ED-LSTM-ED4/12000e-10NR-ED-',
    ]

    pic_path = os.path.join('./vis_background_image', '{}.png'.format(args.test_set))
    args.load = load_list[args.test_set]

    Visualization(pic_path, args)


if __name__ == '__main__':
    main()
