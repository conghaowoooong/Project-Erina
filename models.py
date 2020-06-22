'''
@Author: ConghaoWong
@Date: 2019-12-20 09:39:34
@LastEditors: Conghao Wong
@LastEditTime: 2020-06-22 13:12:40
@Description: classes and methods of training model
'''
import os
import random

import numpy as np
import tensorflow as tf

from tqdm import tqdm
from tensorflow import keras
import matplotlib.pyplot as plt

from helpmethods import(
    list2array,
    dir_check,
    draw_test_results,
)

class __Base_Model():
    """
    Base model for prediction.

    Following items should be given when using this model:
    ```
    self.create_model(self), # create prediction model
    self.loss(self, pred, gt),  # loss function when training model
    self.loss_eval(self, pred, gt), # loss function when test model
    self.forward_train(self, inputs, agents_train='null'), # model result in training steps
    self.forward_test(self, inputs, gt='null', agents_test='null'). # model result in test steps
    ```
    """
    def __init__(self, train_info, args):
        self.args = args
        self.train_info = train_info
        
    def run_commands(self):
        self.initial_dataset()

        if self.args.load == 'null':
            self.model, self.optimizer = self.create_model()
            self.model.summary()
            self.train()
        else:
            self.model, self.agents_test, self.args = self.load_data_and_model()
            self.model.summary()
        
        if self.args.test:
            self.agents_test = self.test(self.agents_test)
            self.draw_pred_results(self.agents_test)

    def initial_dataset(self):
        self.obs_frames = self.args.obs_frames
        self.pred_frames = self.args.pred_frames
        self.total_frames = self.obs_frames + self.pred_frames
        self.log_dir = dir_check(self.args.log_dir)

        if not self.args.load == 'null':
            return

        self.agents_train = self.train_info['train_data']
        self.train_index = self.train_info['train_index']
        self.agents_test = self.train_info['test_data']
        self.test_index = self.train_info['test_index']
        self.train_number = self.train_info['train_number']
        self.sample_time = self.train_info['sample_time'] 
    
    def load_data_and_model(self):
        base_path = self.args.load + '{}'
        model = keras.models.load_model(base_path.format('.h5'))
        agents_test = np.load(base_path.format('test.npy'), allow_pickle=True)
        args = np.load(base_path.format('args.npy'), allow_pickle=True).item()
        return model, agents_test, args
    
    def create_model(self):
        raise 'MODEL is not defined!'
        return model, optimizer

    def loss(self, model_output, gt, obs='null'):
        self.loss_namelist = ['ADE_t']
        loss_ADE = calculate_ADE(model_output[0], gt)
        loss_list = tf.stack([loss_ADE])
        return loss_ADE, loss_list

    def loss_eval(self, model_output, gt, obs='null'):
        self.loss_eval_namelist = ['ADE', 'FDE']
        return calculate_ADE(model_output[0], gt).numpy(), calculate_FDE(model_output[0], gt).numpy()

    def forward(self, input_agents):
        """This method is a direct IO"""
        model_inputs = tf.cast(tf.stack([agent.get_train_traj() for agent in input_agents]), tf.float32)
        outputs = self.model(model_inputs)
        if not type(outputs) == list:
            outputs = [outputs]
        
        pred_traj = outputs[0].numpy()
        for i in range(len(input_agents)):
            input_agents[i].pred = pred_traj[i]
            input_agents[i].pred_fix()
        return input_agents

    def forward_train(self, inputs, agents_train='null'):
        output = self.model(inputs)
        if not type(output) == list:
            output = [output]
        return output

    def __forward_train(self, input_agents):
        input_trajs = tf.cast(tf.stack(
            [traj for agent in input_agents for traj in agent.get_train_traj()]
        ), tf.float32)
        gt = tf.cast(tf.stack(
            [traj for agent in input_agents for traj in agent.get_gt_traj()]
        ), tf.float32)
        return self.forward_train(input_trajs, input_agents), gt, input_trajs

    def forward_test(self, inputs, gt='null', agents_test='null'):
        output = self.model(inputs)
        if not type(output) == list:
            output = [output]
        return output

    def __forward_test(self, input_agents):
        input_trajs = []
        gt = []
        test_index = []
        for index, agent in enumerate(input_agents):
            train_current = agent.get_train_traj()
            gt_current = agent.get_gt_traj()
            for train, g in zip(train_current, gt_current):
                input_trajs.append(train)
                gt.append(g)
                test_index.append(index)

        
        input_trajs = tf.cast(tf.stack(input_trajs), tf.float32)
        gt = tf.cast(tf.stack(gt), tf.float32)
        return self.forward_test(input_trajs, gt, input_agents), gt, input_trajs, test_index

    def test_step(self, input_agents):
        model_output, gt, obs, test_index = self.__forward_test(input_agents)
        loss_eval = self.loss_eval(model_output, gt, obs=obs)
        
        for i, agent in enumerate(input_agents):
            input_agents[i].clear_pred()
            
        for i, output_curr in enumerate(model_output[0]):
            input_agents[test_index[i]].write_pred(output_curr.numpy())

        return model_output, loss_eval, gt, input_agents
    
    def train(self):
        batch_number = int(np.ceil(self.train_number / self.args.batch_size))
        summary_writer = tf.summary.create_file_writer(self.args.log_dir)
        

        print('\n')
        print('-----------------dataset options-----------------')
        if self.args.reverse:
            print('Using reverse data to train. (2x)')
        if self.args.add_noise:
            print('Using noise data to train. ({}x)'.format(self.args.add_noise))
        print('train_number = {}, total {}x train samples.'.format(self.train_number, self.sample_time))

        print('-----------------training options-----------------')
        print('dataset = {},\nbatch_number = {},\nbatch_size = {},\nlr={}'.format(
            self.args.test_set, 
            batch_number, 
            self.args.batch_size,
            self.args.lr,
        ))
        
        print('\n\nStart Training:')
        test_results = []
        test_loss_dict = dict()
        test_loss_dict['-'] = 0
        for epoch in (time_bar := tqdm(range(self.args.epochs))):
            ADE = 0
            ADE_move_average = tf.cast(0.0, dtype=tf.float32)    # 计算移动平均
            loss_list = []
            for batch in range(batch_number):
                batch_start = batch * self.args.batch_size
                batch_end = tf.minimum((batch + 1) * self.args.batch_size, self.train_number)
                agents_current = self.agents_train[batch_start : batch_end]
                index_current = self.train_index[batch_start : batch_end]

                with tf.GradientTape() as tape:
                    model_output_current, gt_current, obs_current = self.__forward_train(agents_current)
                    loss_ADE, loss_list_current = self.loss(model_output_current, gt_current, obs=obs_current)
                    ADE_move_average = 0.7 * loss_ADE + 0.3 * ADE_move_average

                ADE += loss_ADE
                grads = tape.gradient(ADE_move_average, self.model.trainable_variables)
                self.optimizer.apply_gradients(zip(grads, self.model.trainable_variables))

                loss_list.append(loss_list_current)
            
            loss_list = tf.reduce_mean(tf.stack(loss_list), axis=0).numpy()

            if (epoch >= self.args.start_test_percent * self.args.epochs) and (epoch % self.args.test_step == 0):
                model_output, loss_eval, _, _ = self.test_step(self.agents_test)
                test_results.append(loss_eval)
                test_loss_dict = create_loss_dict(loss_eval, self.loss_eval_namelist)
            
            train_loss_dict = create_loss_dict(loss_list, self.loss_namelist)
            loss_dict = dict(train_loss_dict, **test_loss_dict) # 拼接字典
            time_bar.set_postfix(loss_dict)

            with summary_writer.as_default():
                for loss_name in loss_dict:
                    value = loss_dict[loss_name]
                    tf.summary.scalar(loss_name, value, step=epoch)

        print('Training done.')
        print('Tensorboard training log file is saved at "{}"'.format(self.args.log_dir))
        print('To open this log file, please use "tensorboard --logdir {} --port 54393"'.format(self.args.log_dir))
        
        latest_epochs = 10
        test_results = list2array(test_results)
        latest_results = np.mean(test_results[-latest_epochs-1:-1, :], axis=0)
        print('In latest {} test epochs, average test loss = {}'.format(
            latest_epochs,
            latest_results
        ))
        np.savetxt(os.path.join(self.args.log_dir, 'train_log.txt'), list2array(test_results))

        if self.args.save_model:
            self.model_save_path = os.path.join(self.args.log_dir, '{}.h5'.format(self.args.model_name))
            self.test_data_save_path = os.path.join(self.args.log_dir, '{}.npy'.format(self.args.model_name + '{}'))
            self.model.save(self.model_save_path)
            np.save(self.test_data_save_path.format('test'), self.agents_test)   
            np.save(self.test_data_save_path.format('args'), self.args)
            print('Trained model is saved at "{}".'.format(self.model_save_path.split('.h5')[0]))
            print('To re-test this model, please use "python main.py --load {}".'.format(self.model_save_path.split('.h5')[0]))
    
    def test(self, agents_test):
        test_agents_number = len(agents_test)
        print('Start test:')    
        model_output, loss_eval, gt_test, agents_test = self.test_step(agents_test)
        pred_traj = model_output[0].numpy()
        # for i in range(len(agents_test)):
        #     agents_test[i].pred = pred_traj[i]

        print('test_loss={}'.format(create_loss_dict(loss_eval, self.loss_eval_namelist)))
        for loss in loss_eval:
            print(loss, end='\t')
        print('\nTest done.')
        return agents_test

    def draw_pred_results(self, agents):
        print('\n\nSaving Results:')
        draw_test_results(
            agents, 
            self.log_dir, 
            loss_function=calculate_ADE_single, 
            save=self.args.draw_results,
            train_base=self.args.train_base,
        )


class LSTM_FC(__Base_Model):
    """
    LSTM based model with full attention layer.
    """
    def __init__(self, train_info, args):
        super().__init__(train_info, args)

    def create_model(self):
        positions = keras.layers.Input(shape=[self.obs_frames, 2])
        positions_embadding = keras.layers.Dense(64)(positions)
        traj_feature = keras.layers.LSTM(64)(positions_embadding)
        output3 = keras.layers.Dense(self.pred_frames * 16)(traj_feature)
        output4 = keras.layers.Reshape([self.pred_frames, 16])(output3)
        output5 = keras.layers.Dense(2)(output4)
        lstm = keras.Model(inputs=positions, outputs=[output5], name='LSTM_FC')

        lstm.build(input_shape=[None, self.obs_frames, 2])
        lstm_optimizer = keras.optimizers.Adam(lr=self.args.lr)
        
        return lstm, lstm_optimizer


class LSTM_FC_hardATT(__Base_Model):
    """
    LSTM based model with full attention layer.
    """
    def __init__(self, train_info, args):
        self.frame_index = tf.constant(args.frame)
        super().__init__(train_info, args)

    def create_model(self):
        positions = keras.layers.Input(shape=[len(self.args.frame), 2])    # use 4 frames of input
        positions_embadding = keras.layers.Dense(64)(positions)
        traj_feature = keras.layers.LSTM(64)(positions_embadding)
        output3 = keras.layers.Dense(self.pred_frames * 16)(traj_feature)
        output4 = keras.layers.Reshape([self.pred_frames, 16])(output3)
        output5 = keras.layers.Dense(2)(output4)
        lstm = keras.Model(inputs=positions, outputs=[output5], name='LSTM_FC')

        lstm.build(input_shape=[None, self.obs_frames, 2])
        lstm_optimizer = keras.optimizers.Adam(lr=self.args.lr)
        
        return lstm, lstm_optimizer

    def forward_train(self, inputs, agents_train='null'):
        inputs = tf.gather(inputs, self.frame_index, axis=1)
        output = self.model(inputs)
        if not type(output) == list:
            output = [output]
        return output

    def forward_test(self, inputs, gt='null', agents_test='null'):
        inputs = tf.gather(inputs, self.frame_index, axis=1)
        output = self.model(inputs)
        if not type(output) == list:
            output = [output]
        return output


class LSTM_FC_develop_beta(__Base_Model):
    def __init__(self, train_info, args):
        super().__init__(train_info, args)

    def create_model(self):
        positions = keras.layers.Input(shape=[self.obs_frames, 2])
        positions_embadding = keras.layers.Dense(64)(positions)
        traj_feature = keras.layers.LSTM(64)(positions_embadding)
        concat_feature = tf.concat([traj_feature, positions_embadding[:, -1, :]], axis=-1)
        output3 = keras.layers.Dense(self.pred_frames * 32)(concat_feature)
        output4 = keras.layers.Reshape([self.pred_frames, 32])(output3)
        output5 = keras.layers.Dense(2)(output4)
        lstm = keras.Model(inputs=positions, outputs=[output5])

        lstm.build(input_shape=[None, self.obs_frames, 2])
        lstm_optimizer = keras.optimizers.Adam(lr=self.args.lr)
        
        return lstm, lstm_optimizer


class SS_LSTM(__Base_Model):
    """
    `S`tate and `S`equence `LSTM`
    """
    def __init__(self, train_info, args):
        super().__init__(train_info, args)

    def create_model(self):
        positions = keras.layers.Input(shape=[self.obs_frames, 2])
        positions_embadding = keras.layers.Dense(64)(positions)
        traj_feature = keras.layers.LSTM(64, return_sequences=True)(positions_embadding)

        concat_feature = tf.concat([traj_feature, positions_embadding], axis=-1)
        feature_flatten = tf.reshape(concat_feature, [-1, self.obs_frames * 64 * 2])
        feature_fc = keras.layers.Dense(self.pred_frames * 64)(feature_flatten)
        feature_reshape = tf.reshape(feature_fc, [-1, self.pred_frames, 64])
        output5 = keras.layers.Dense(2)(feature_reshape)
        lstm = keras.Model(inputs=positions, outputs=[output5])

        lstm.build(input_shape=[None, self.obs_frames, 2])
        lstm_optimizer = keras.optimizers.Adam(lr=self.args.lr)
        
        return lstm, lstm_optimizer


class LSTMcell(__Base_Model):
    """
    Recurrent cell of LSTM
    """
    def __init__(self, train_info, args):
        super().__init__(train_info, args)
        
    def create_model(self):
        feature_dim = 64
        embadding = keras.layers.Dense(feature_dim)
        cell = keras.layers.LSTMCell(feature_dim)
        decoder = keras.layers.Dense(2)
        positions = keras.layers.Input(shape=[self.obs_frames, 2])

        h = tf.transpose(tf.stack([tf.reduce_sum(tf.zeros_like(positions), axis=[1, 2]) for _ in range(feature_dim)]), [1, 0])
        c = tf.zeros_like(h)
        
        state_init = [h, c]
        for frame in range(self.obs_frames):
            input_current = positions[:, frame, :]
            input_current_embadding = embadding(input_current)
            h_new, [_, c_new] = cell(input_current_embadding, [h, c])
            output_current = decoder(h_new)
            [h, c] = [h_new, c_new]
        
        all_output = []
        for frame in range(self.pred_frames):
            input_current_embadding = embadding(output_current)
            h_new, [_, c_new] = cell(input_current_embadding, [h, c])
            output_current = decoder(h_new)
            [h, c] = [h_new, c_new]

            all_output.append(output_current)
        
        output = tf.transpose(tf.stack(all_output), [1, 0, 2])

        lstm = keras.Model(inputs=positions, outputs=[output])
        lstm.build(input_shape=[None, self.obs_frames, 2])
        lstm_optimizer = keras.optimizers.Adam(lr=self.args.lr)
        
        return lstm, lstm_optimizer
        


class FC_cycle(__Base_Model):
    def __init__(self, train_info, args):
        super().__init__(train_info, args)

    def create_model(self):
        embadding = keras.layers.Dense(64)
        LSTM = keras.layers.LSTM(64)
        MLP = keras.layers.Dense(self.pred_frames * 2*self.obs_frames)

        inputs = keras.layers.Input(shape=[self.obs_frames, 2])
        output1 = embadding(inputs)
        output2 = LSTM(output1)
        output3 = MLP(output2)
        output4 = keras.layers.Reshape([self.pred_frames, 2*self.obs_frames])(output3)
        output5 = keras.layers.Dense(2)(output4)    #shape=[batch, 12, 2]

        output5_reverse = tf.reverse(output5, axis=[1])
        output6 = embadding(output5_reverse)
        output7 = LSTM(output6)  # shape=[12, 64]
        output8 = MLP(output7)
        output9 = keras.layers.Reshape([self.obs_frames, 2*self.pred_frames])(output8)
        rebuild = keras.layers.Dense(2)(output9)
        rebuild_reverse = tf.reverse(rebuild, [1])
        
        lstm = keras.Model(inputs=inputs, outputs=[output5, rebuild_reverse])

        lstm.build(input_shape=[None, self.obs_frames, 2])
        lstm_optimizer = keras.optimizers.Adam(lr=self.args.lr)
        
        return lstm, lstm_optimizer

    def loss(self, model_output, gt, obs='null'):
        self.loss_namelist = ['ADE_t', 'rebuild_t']
        predict = model_output[0]
        rebuild = model_output[1]
        loss_ADE = calculate_ADE(predict, gt)
        loss_rebuild = calculate_ADE(rebuild, obs)
        loss_list = tf.stack([loss_ADE, loss_rebuild])
        return 1.0 * loss_ADE + 0.4 * loss_rebuild, loss_list

    def loss_eval(self, model_output, gt, obs='null'):
        self.loss_eval_namelist = ['ADE', 'FDE', 'L2_rebuild']
        predict = model_output[0]
        rebuild = model_output[1]
        loss_ADE = calculate_ADE(predict, gt).numpy()
        loss_FDE = calculate_FDE(predict, gt).numpy()
        loss_rebuild = calculate_ADE(rebuild, obs).numpy()

        return loss_ADE, loss_FDE, loss_rebuild


class LSTM_ED(__Base_Model):
    def __init__(self, train_info, args):
        super().__init__(train_info, args)
        self.fc_size = 16
        self.feature_layer = 3 + 1  # Input is also a layer
        self.output_layer = 6 + 1

    def create_model(self):
        inputs = keras.Input(shape=[self.obs_frames, 2])
        output0 = keras.layers.Dense(64, activation=tf.nn.relu)(inputs)
        output1 = keras.layers.Dropout(self.args.dropout)(output0)
        output2 = keras.layers.LSTM(128)(output1)                        # 2
        output3 = keras.layers.Dense(self.pred_frames * self.fc_size, activation=tf.nn.relu)(output2)      # 3
        output4 = keras.layers.Reshape([self.pred_frames, self.fc_size])(output3)   # 4
        output5 = keras.layers.LSTM(64, return_sequences=True)(output4)   # 5
        output6 = keras.layers.Dense(2)(output5)

        position_output = output6
        feature_output = output3

        ae = keras.Model(inputs=[inputs], outputs=[position_output, feature_output])
        ae.build(input_shape=[None, self.obs_frames, 2])
        ae_optimizer = keras.optimizers.Adam(lr=self.args.lr)
        print(ae.summary())
        return ae, ae_optimizer
    
    def forward_test(self, inputs_test, groundtruth_test, agents_test='null'):
        batch = inputs_test.shape[0]
        self.noise_mean = 0.0
        self.noise_sigma = 0.1

        test_results = []
        for re in range(self.args.k):
            # print('Repeat step {}/{}...\t'.format(re, self.args.k), end='\r')
            noise = np.random.normal(self.noise_mean, self.noise_sigma, size=[batch, self.pred_frames * self.fc_size])
            features = get_model_outputs(self.model, inputs_test, input_layer=0, output_layer=self.feature_layer)
            position_output = get_model_outputs(self.model, features + noise, input_layer=self.feature_layer+1, output_layer=self.output_layer)
            test_results.append(position_output.numpy())
        print('Generate done.')

        self.loss_eval_namelist = ['ADE', 'FDE', 'mADE', 'mFDE', 'sA', 'sF', 'GP_ADE', 'GP_FDE']
        test_results = np.transpose(list2array(test_results), axes=[1, 0, 2, 3])
        return [tf.cast(test_results, tf.float32)]
    
    def loss(self, model_output, gt, obs='null'):
        self.loss_namelist = ['ADE_t', 'smooth_t']
        loss_ADE = calculate_ADE(model_output[0], gt)
        loss_smoothness = smooth_loss(obs, model_output[0], step=1)
        loss_list = tf.stack([loss_ADE, loss_smoothness])
        return 1.0 * loss_ADE + 0.0 * loss_smoothness, loss_list
    
    def loss_eval(self, model_output, gt, obs='null'):
        self.loss_eval_namelist = ['ADE', 'FDE', 'mADE', 'mFDE', 'sA', 'sF', 'GP_ADE', 'GP_FDE', 'smooth']
        return self.choose_best_path(model_output[0], gt)[1]
    
    def choose_best_path(self, positions, groundtruth, choose='best'):
        positions = tf.cast(positions, tf.float32)
        groundtruth = tf.cast(groundtruth, tf.float32)
        positions = tf.transpose(positions, [1, 0, 2, 3])

        all_ADE = tf.reduce_mean(tf.linalg.norm(positions - groundtruth, ord=2, axis=3), axis=2)
        all_FDE = tf.linalg.norm(positions[:, :, -1, :] - groundtruth[:, -1, :], ord=2, axis=2)

        mean_traj = tf.reduce_mean(positions, axis=0)
        GP_ADE = tf.reduce_mean(tf.linalg.norm(mean_traj - groundtruth, ord=2, axis=2), axis=1)
        GP_FDE = tf.linalg.norm(mean_traj[:, -1, :] - groundtruth[:, -1, :], ord=2, axis=1)

        mean_ADE = tf.reduce_mean(all_ADE, axis=0)
        mean_FDE = tf.reduce_mean(all_FDE, axis=0)

        s_ADE = tf.math.reduce_std(all_ADE, axis=0)
        s_FDE = tf.math.reduce_std(all_FDE, axis=0)

        minADE_index = tf.cast(tf.argmin(all_ADE, axis=0), tf.int32)
        minADE_index = tf.transpose(tf.stack([
            tf.stack([i for i in range(minADE_index.shape[0])]),
            minADE_index,
        ]))
        positions = tf.transpose(positions, [1, 0, 2, 3])
        traj = tf.gather_nd(positions, minADE_index)
        ADE = tf.gather_nd(tf.transpose(all_ADE), minADE_index)
        FDE = tf.gather_nd(tf.transpose(all_FDE), minADE_index)

        result = traj
        ADE_FDE = tf.stack([
            ADE, FDE, mean_ADE, mean_FDE, s_ADE, s_FDE, GP_ADE, GP_FDE
        ])
        ADE_FDE = tf.reduce_mean(ADE_FDE, axis=1)

        if self.args.save_k_results:
            save_format = os.path.join(self.args.log_dir, '{}.npy')
            np.save(save_format.format('best'), result)
            np.save(save_format.format('all'), positions)
            np.save(save_format.format('gt'), groundtruth)
            np.save(save_format.format('mean'), mean_traj)

        return result, ADE_FDE.numpy()


class Linear(__Base_Model):
    def __init__(self, train_info, args):
        super().__init__(train_info, args)
        self.args.batch_size = 1
        self.args.epochs = 1
        self.args.draw_results = False
        self.args.train_percent = 0.0
    
    def run_commands(self):
        self.initial_dataset()
        self.model, self.optimizer = self.create_model()
        self.test(self.agents_test)

    def predict_linear(self, x, y, x_p, diff_weights=0):
        if diff_weights == 0:
            P = np.diag(np.ones(shape=[x.shape[0]]))
        else:
            P = np.diag(softmax([(i+1)**diff_weights for i in range(x.shape[0])]))

        A = tf.transpose(tf.stack([np.ones_like(x), x]))
        A_p = tf.transpose(tf.stack([np.ones_like(x_p), x_p]))
        Y = tf.transpose(y)

        P = tf.cast(P, tf.float32)
        A = tf.cast(A, tf.float32)
        A_p = tf.cast(A_p, tf.float32)
        Y = tf.reshape(tf.cast(Y, tf.float32), [-1, 1])
        
        B = tf.matmul(tf.matmul(tf.matmul(tf.linalg.inv(tf.matmul(tf.matmul(tf.transpose(A), P), A)), tf.transpose(A)), P), Y)
        Y_p = np.matmul(A_p, B)
        return Y_p, B

    def predict_linear_for_person(self, positions, diff_weights):
        t = np.array([t for t in range(self.obs_frames)])
        t_p = np.array([t + self.obs_frames for t in range(self.pred_frames)])
        x = tf.transpose(positions)[0]
        y = tf.transpose(positions)[1]

        x_p, _ = self.predict_linear(t, x, t_p, diff_weights=diff_weights)
        y_p, _ = self.predict_linear(t, y, t_p, diff_weights=diff_weights)

        return tf.transpose(tf.reshape(tf.stack([x_p, y_p]), [2, self.pred_frames]))
    
    def create_model(self):
        return self.predict_linear_for_person, 0

    def forward_train(self, inputs, agents_train='null'):
        results = []
        for inputs_current in inputs:
            results.append(self.model(inputs_current, diff_weights=self.args.diff_weights))
        
        return [tf.stack(results)]

    def forward_test(self, inputs, gt='null', agents_train='null'):
        results = []
        for inputs_current in inputs:
            results.append(self.model(inputs_current, diff_weights=self.args.diff_weights))
        
        return [tf.stack(results)]

    

"""
helpmethods
"""

def draw_one_traj(traj, GT, save_path):
    plt.figure()

    plt.plot(traj.T[0], traj.T[1], '-*')
    plt.plot(GT.T[0], GT.T[1], '-o')
    plt.axis('scaled')

    plt.savefig(save_path)
    plt.close()


def create_loss_dict(loss, name_list):
        return dict(zip(name_list, loss))


def softmax(x):
    return np.exp(x)/np.sum(np.exp(x),axis=0)


def calculate_ADE_single(pred, GT):
    """input_shape = [pred_frames, 2]"""
    if not len(pred.shape) == 3:
        pred = tf.reshape(pred, [1, pred.shape[0], pred.shape[1]])
    
    pred = tf.cast(pred, tf.float32)
    GT = tf.cast(GT, tf.float32)
    return tf.reduce_mean(tf.linalg.norm(pred - GT, ord=2, axis=2))


def calculate_ADE(pred, GT):
    """input_shape = [batch, pred_frames, 2]"""
    pred = tf.cast(pred, tf.float32)
    GT = tf.cast(GT, tf.float32)
    return tf.reduce_mean(tf.linalg.norm(pred - GT, ord=2, axis=2))
    

def calculate_FDE(pred, GT):
    pred = tf.cast(pred, tf.float32)
    GT = tf.cast(GT, tf.float32)
    return tf.reduce_mean(tf.linalg.norm(pred[:, -1, :] - GT[:, -1, :], ord=2, axis=1))


def get_model_outputs(model, inputs, input_layer=0, output_layer=1):
    inn = inputs
    for i in range(input_layer, output_layer+1):
        layer = model.get_layer(index=i)
        output = layer(inn)
        inn = output
    return output


def smooth_loss(obs, pred, step=2, return_min=True, as_loss=True):
    """
    shape for inputs:
    
    `obs`: [batch, obs_frames, 2]
    `pred`: [batch, pred_frames, 2]
    """
    start_point = obs[:, -step:, :]
    pred_frames = pred.shape[1]

    score_list = []
    delta = []
    for frame in range(step):
        delta.append(pred[:, frame] - start_point[:, frame])

    for frame in range(step, pred_frames):
        delta.append(pred[:, frame] - pred[:, frame-step])
    
    delta = tf.transpose(tf.stack(delta), [1, 0, 2])
    cosine_list = tf.stack([calculate_cosine(delta[:, frame-1, :], delta[:, frame, :]) for frame in range(1, pred_frames)])

    if return_min:
        cosine_list = tf.reduce_min(cosine_list, axis=0)
    
    if as_loss:
        cosine_list = tf.reduce_mean(1.0 - cosine_list)
    
    return cosine_list


def calculate_cosine(p1, p2, absolute=True):
    """
    shape for inputs:
    
    `p1`: [batch, 2]
    `p2`: [batch, 2]
    """
    l_p1 = tf.linalg.norm(p1, axis=1)
    l_p2 = tf.linalg.norm(p2, axis=1)
    dot = tf.reduce_sum(p1 * p2, axis=1)
    result = dot/(l_p1 * l_p2)
    if absolute:
        result = tf.abs(result)
    return result
    

def save_visable_weighits(model, layer_name, if_abs=True, save_path='./test.png'):
    """This method is only for test"""
    import cv2
    weights = model.get_layer(layer_name).get_weights()[0]
    if if_abs:
        weights = np.abs(weights)
    
    weights_norm = (weights - weights.min())/(weights.max() - weights.min())
    weights_draw = (255 * weights_norm).astype(np.int)
    cv2.imwrite(save_path, weights_draw)
