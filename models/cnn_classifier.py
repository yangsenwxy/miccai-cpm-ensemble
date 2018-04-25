import os

import tensorflow as tf
import numpy as np

from models.model import Model
from utils.data_utils import get_ex_paths, get_hgg_and_lgg_patients
from utils.dataset_v3 import get_dataset_v3, get_dataset_single_patient_v3, get_dataset_batched
from utils.general import Progbar
from utils.lr_schedule import LRSchedule


class CNN_Classifier(Model):
    def __init__(self, config):
        self.config = config
        self.patch = config.patch_size
        self.nb_classes = config.nb_classes
        self.nb_modalities = config.use_t1pre + config.use_t1post + config.use_t2 + config.use_flair

        self.load_data()
        self.add_dataset()
        self.add_placeholders()
        self.add_model()
        self.add_pred_op()
        self.add_loss_op()
        self.add_train_op()

    def load_data(self):
        self.train_ex_paths = get_ex_paths(self.config.train_path)
        self.val_ex_paths = get_ex_paths(self.config.val_path)

    def add_dataset(self):
        train_dataset = get_dataset_batched(self.config.train_path, False, self.config)
        test_dataset = get_dataset_batched(self.config.val_path, True, self.config)
        # iterator just needs to know the output types and shapes of the datasets
        self.iterator = tf.contrib.data.Iterator.from_structure(
            output_types=(tf.float32,
                          tf.int32,
                          tf.bool),
            output_shapes=([None, 240, 240, 155, 4],
                           [None, 240, 240, 155],
                           [None]))
        self.image, self.label, self.mgmtmethylated = self.iterator.get_next()
        self.train_init_op = self.iterator.make_initializer(train_dataset)
        self.test_init_op = self.iterator.make_initializer(test_dataset)

    def add_placeholders(self):
        self.image_placeholder = tf.placeholder(tf.float32,
                                                shape=[None, self.patch, self.patch, self.patch, 4])
        self.label_placeholder = tf.placeholder(tf.int32,
                                                shape=[None, self.patch, self.patch, self.patch])
        self.dropout_placeholder = tf.placeholder(tf.float32, shape=[])
        self.lr_placeholder = tf.placeholder(tf.float32, shape=[])
        self.is_training = tf.placeholder(tf.bool, shape=[])

        # for tensorboard
        tf.summary.scalar("lr", self.lr_placeholder)

    def add_summary(self, sess):
        # tensorboard stuff
        # hardcoded
        # TODO: do it properly
        name_exp = self.config.res_path.strip().split('/')[1][:-4]
        summary_path = os.path.join('summaries', name_exp)
        self.merged = tf.summary.merge_all()
        self.file_writer = tf.summary.FileWriter(summary_path, sess.graph)

    def get_variables_to_restore(self):
        # to initialize some variables with pretained weights
        # 'level' refers to a level in the V-net architecture
        var_names_to_restore = ['conv1/conv3d/kernel:0',
                                'conv1/conv3d/bias:0',
                                'conv2/conv3d/kernel:0',
                                'conv2/conv3d/bias:0',
                                'conv3/conv3d/kernel:0',
                                'conv3/conv3d/bias:0',
                                'predict/dense/kernel:0',
                                'predict/dense/bias:0']

        var_to_restore = tf.contrib.framework.get_variables_to_restore(include=var_names_to_restore)
        var_to_train = tf.contrib.framework.get_variables_to_restore(exclude=var_names_to_restore)
        # print('*' * 50 + 'variables to retrain' + '*' * 50)
        # print([var.name for var in var_to_train])
        # print('*' * 50 + 'variables to restore' + '*' * 50)
        # print([var.name for var in var_to_restore])
        return var_to_train, var_to_restore

    def run_epoch(self, sess, lr_schedule, finetune=False):
        losses = []
        bdices = []
        batch = 0

        nbatches = len(self.train_ex_paths)
        prog = Progbar(target=nbatches)

        sess.run(self.train_init_op)

        while True:
            try:
                feed = {self.dropout_placeholder: self.config.dropout,
                        self.lr_placeholder: lr_schedule.lr,
                        self.is_training: self.config.use_batch_norm}

                if finetune:
                    pred, loss, summary, global_step, _ = sess.run([self.pred, self.loss,
                                                                    self.merged, self.global_step,
                                                                    self.train_last_layers],
                                                                   feed_dict=feed)
                else:
                    pred, loss, summary, global_step, _ = sess.run([self.pred, self.loss,
                                                                    self.merged, self.global_step,
                                                                    self.train],
                                                                   feed_dict=feed)
                batch += self.config.batch_size
            except tf.errors.OutOfRangeError:
                break

            losses.append(loss)

            # logging
            prog.update(batch, values=[("loss", loss)], exact=[("lr", lr_schedule.lr),
                                                               ('score', lr_schedule.score)])
            # for tensorboard
            self.file_writer.add_summary(summary, global_step)

        return losses, np.mean(bdices)

    def run_test_v3(self, sess):
        sess.run(self.test_init_op)
        current_patient = ""

        all_dices_whole = []
        all_dices_core = []
        all_dices_enhancing = []

        HGG_patients, LGG_patients = get_hgg_and_lgg_patients(self.config.val_path)

        HGG_dices_whole = []
        HGG_dices_core = []
        HGG_dices_enhancing = []

        LGG_dices_whole = []
        LGG_dices_core = []
        LGG_dices_enhancing = []

        center = self.config.center_patch
        half_center = center // 2
        lower = self.patch // 2 - half_center

        print('Validation ...')
        while True:
            feed = {self.dropout_placeholder: 1.0,
                    self.is_training: False}
            try:
                patients, pat_shapes, i, j, k, y, pred = sess.run([self.pat_path, self.pat_shape,
                                                                   self.i, self.j, self.k,
                                                                   self.label, self.pred],
                                                                  feed_dict=feed)
            except tf.errors.OutOfRangeError:
                break

            for idx, _ in enumerate(i):
                if patients[idx] != current_patient:
                    if current_patient != "":
                        # compute dice scores for different classes
                        # dice score for the Whole Tumor
                        dice_whole = dice_score(fy, fpred)
                        all_dices_whole.append(dice_whole)
                        if current_patient in HGG_patients:
                            HGG_dices_whole.append(dice_whole)
                        if current_patient in LGG_patients:
                            LGG_dices_whole.append(dice_whole)
                        # print('dice score of whole of patient %s is %f'%(current_patient, dice_whole))

                        if self.nb_classes > 2:
                            # dice score for Tumor Core
                            fpred_core = (fpred == 1) + (fpred == 3)
                            fy_core = (fy == 1) + (fy == 3)
                            dice_core = dice_score(fy_core, fpred_core)
                            all_dices_core.append(dice_core)
                            if current_patient in HGG_patients:
                                HGG_dices_core.append(dice_core)
                            if current_patient in LGG_patients:
                                LGG_dices_core.append(dice_core)
                            # print('dice score of core of patient %s is %f'%(current_patient, dice_core))

                            # dice score for Enhancing Tumor
                            fpred_enhancing = fpred == 3
                            fy_enhancing = fy == 3
                            dice_enhancing = dice_score(fy_enhancing, fpred_enhancing)
                            all_dices_enhancing.append(dice_enhancing)
                            if current_patient in HGG_patients:
                                HGG_dices_enhancing.append(dice_enhancing)
                            if current_patient in LGG_patients:
                                LGG_dices_enhancing.append(dice_enhancing)
                            # print('dice score of enhancing of patient %s is %f'%(current_patient, dice_enhancing))

                    fpred = np.zeros(eval(pat_shapes[idx]))
                    fy = np.zeros(eval(pat_shapes[idx]))
                    current_patient = patients[idx]

                fy[i[idx] - half_center:i[idx] + half_center,
                j[idx] - half_center:j[idx] + half_center,
                k[idx] - half_center:k[idx] + half_center] = y[idx, :, :, :]
                fpred[i[idx] - half_center:i[idx] + half_center,
                j[idx] - half_center:j[idx] + half_center,
                k[idx] - half_center:k[idx] + half_center] = pred[idx, lower:lower + center, \
                                                             lower:lower + center, lower:lower + center]

        return np.mean(all_dices_whole), np.mean(all_dices_core), np.mean(all_dices_enhancing), \
               np.mean(HGG_dices_whole), np.mean(HGG_dices_core), np.mean(HGG_dices_enhancing), \
               np.mean(LGG_dices_whole), np.mean(LGG_dices_core), np.mean(LGG_dices_enhancing)

    def run_pred_single_example_v3(self, sess, patient):
        if b'brats' in patient:
            name_dataset = 'Brats'
        elif b'TCGA' in patient:
            name_dataset = 'TCGA'
        else:
            name_dataset = 'not Brats'

        dataset = get_dataset_single_patient_v3(patient, self.config, name_dataset)
        init_op = self.iterator.make_initializer(dataset)
        sess.run(init_op)

        center = self.config.center_patch
        half_center = center // 2
        lower = self.patch // 2 - half_center
        fpred = None

        while True:
            try:
                feed = {self.dropout_placeholder: 1.0,
                        self.is_training: False}
                pat_shape, i, j, k, pred = sess.run([self.pat_shape, self.i, self.j, self.k, self.pred], feed_dict=feed)
            except tf.errors.OutOfRangeError:
                break

            if fpred is None:
                fpred = np.zeros(eval(pat_shape[0]))

            for idx, _ in enumerate(i):
                fpred[i[idx] - half_center:i[idx] + half_center,
                j[idx] - half_center:j[idx] + half_center,
                k[idx] - half_center:k[idx] + half_center] = pred[idx, lower:lower + center, \
                                                             lower:lower + center, lower:lower + center]

        return fpred

    def full_train(self, sess):
        config = self.config

        nbatches = len(self.train_ex_paths) * config.num_train_batches
        exp_decay = np.power(config.lr_min / config.lr_init, \
                             1 / float(config.end_decay - config.start_decay))
        lr_schedule = LRSchedule(lr_init=config.lr_init, lr_min=config.lr_min,
                                 start_decay=config.start_decay * nbatches,
                                 end_decay=config.end_decay * nbatches,
                                 lr_warm=config.lr_warm, decay_rate=config.decay_rate,
                                 end_warm=config.end_warm * nbatches, exp_decay=exp_decay)

        saver = tf.train.Saver()

        # for tensorboard
        self.add_summary(sess)

        train_losses = []
        train_bdices = []
        test_whole_dices = []
        test_core_dices = []
        test_enhancing_dices = []
        best_fdice = 0

        print('Start training ....')
        for epoch in range(1, config.num_epochs + 1):
            print('Epoch %d ...' % epoch)
            losses, train_dice = self.run_epoch(sess, lr_schedule)
            train_losses.extend(losses)
            train_bdices.append(train_dice)

            if epoch % 2 == 0:
                # test_whole, test_core, test_enhancing, _, _, _, _, _, _ = self.run_test(sess)
                test_whole, test_core, test_enhancing, _, _, _, _, _, _ = self.run_test_v3(sess)
                print('End of test, whole dice score is %f, core dice score is %f and enhancing dice score is %f' \
                      % (test_whole, test_core, test_enhancing))
                # logging
                test_whole_dices.append(test_whole)
                test_core_dices.append(test_core)
                test_enhancing_dices.append(test_enhancing)
                lr_schedule.update(batch_no=epoch * nbatches, score=test_core + test_enhancing)

                if test_core + test_enhancing >= best_fdice:
                    best_fdice = test_core + test_enhancing

                    print('Saving checkpoint to %s ......' % (config.ckpt_path))
                    saver.save(sess, config.ckpt_path)

                    print('Saving results to %s ......' % (config.res_path))
                    np.savez(config.res_path,
                             train_losses=train_losses,
                             train_bdices=train_bdices,
                             test_whole_dices=test_whole_dices,
                             test_core_dices=test_core_dices,
                             test_enhancing_dices=test_enhancing_dices,
                             train_ex_paths=self.train_ex_paths,
                             val_ex_paths=self.val_ex_paths,
                             config_file=config.__dict__)

            else:
                lr_schedule.update(batch_no=epoch * nbatches)

        return test_whole

    def add_train_op(self):
        self.global_step = tf.train.get_or_create_global_step()
        update_ops = tf.get_collection(tf.GraphKeys.UPDATE_OPS)
        with tf.control_dependencies(update_ops):
            self.train = tf.train.AdamOptimizer(learning_rate=self.lr_placeholder) \
                .minimize(self.loss, global_step=self.global_step)

            if self.config.finetuning_method == 'last_layers':
                var_to_train, _ = self.get_variables_to_restore()
                self.train_last_layers = tf.train.AdamOptimizer(learning_rate=self.lr_placeholder) \
                    .minimize(self.loss, var_list=var_to_train,
                              global_step=self.global_step)

    def add_model(self):
        self.image = tf.reshape(self.image, [-1, self.patch, self.patch, self.patch, self.nb_modalities])
        nb_filters = self.config.nb_filters
        k_size = self.config.kernel_size

        with tf.variable_scope('conv1'):
            conv1_1 = tf.layers.conv3d(inputs=self.image,
                                       filters=nb_filters,
                                       kernel_size=k_size,
                                       strides=(1, 1, 1),
                                       padding='SAME',
                                       activation=None,
                                       use_bias=True,
                                       kernel_initializer=tf.contrib.layers.xavier_initializer(),
                                       bias_initializer=tf.constant_initializer(0.0),
                                       kernel_regularizer=tf.nn.l2_loss)
            bn1_1 = tf.layers.batch_normalization(conv1_1, axis=-1, training=self.is_training)
            relu1_1 = tf.nn.relu(bn1_1)

            conv1_2 = tf.layers.conv3d(inputs=relu1_1,
                                       filters=nb_filters,
                                       kernel_size=k_size,
                                       strides=(1, 1, 1),
                                       padding='SAME',
                                       activation=None,
                                       use_bias=True,
                                       kernel_initializer=tf.contrib.layers.xavier_initializer(),
                                       bias_initializer=tf.constant_initializer(0.0),
                                       kernel_regularizer=tf.nn.l2_loss)
            bn1_2 = tf.layers.batch_normalization(conv1_2, axis=-1, training=self.is_training)
            relu1_2 = tf.nn.relu(bn1_2)

            # shape = (patch/2, patch/2, patch/2)
            pool1_2 = tf.layers.max_pooling3d(inputs=relu1_2, pool_size=(2, 2, 2),
                                              strides=(2, 2, 2), padding='VALID')

            # drop1 = tf.nn.dropout(pool1_2, self.dropout_placeholder)

        with tf.variable_scope('conv2'):
            conv2_1 = tf.layers.conv3d(inputs=pool1_2,
                                       filters=2 * nb_filters,
                                       kernel_size=k_size,
                                       strides=(1, 1, 1),
                                       padding='SAME',
                                       activation=None,
                                       use_bias=True,
                                       kernel_initializer=tf.contrib.layers.xavier_initializer(),
                                       bias_initializer=tf.constant_initializer(0.0),
                                       kernel_regularizer=tf.nn.l2_loss)

            bn2_1 = tf.layers.batch_normalization(conv2_1, axis=-1, training=self.is_training)
            relu2_1 = tf.nn.relu(bn2_1)

            conv2_2 = tf.layers.conv3d(inputs=relu2_1,
                                       filters=2 * nb_filters,
                                       kernel_size=k_size,
                                       strides=(1, 1, 1),
                                       padding='SAME',
                                       activation=None,
                                       use_bias=True,
                                       kernel_initializer=tf.contrib.layers.xavier_initializer(),
                                       bias_initializer=tf.constant_initializer(0.0),
                                       kernel_regularizer=tf.nn.l2_loss)

            bn2_2 = tf.layers.batch_normalization(conv2_2, axis=-1, training=self.is_training)
            relu2_2 = tf.nn.relu(bn2_2)

            # shape = (patch/4, patch/4, patch/4)
            pool2_2 = tf.layers.max_pooling3d(inputs=relu2_2, pool_size=(2, 2, 2),
                                              strides=(2, 2, 2), padding='VALID')
            # drop2 = tf.nn.dropout(pool2, self.dropout_placeholder)

        with tf.variable_scope('conv3'):
            conv3_1 = tf.layers.conv3d(inputs=pool2_2,
                                       filters=4 * nb_filters,
                                       kernel_size=k_size,
                                       strides=(1, 1, 1),
                                       padding='SAME',
                                       activation=None,
                                       use_bias=True,
                                       kernel_initializer=tf.contrib.layers.xavier_initializer(),
                                       bias_initializer=tf.constant_initializer(0.0),
                                       kernel_regularizer=tf.nn.l2_loss)

            bn3_1 = tf.layers.batch_normalization(conv3_1, axis=-1, training=self.is_training)
            relu3_1 = tf.nn.relu(bn3_1)
            drop3_1 = tf.nn.dropout(relu3_1, self.dropout_placeholder)

            conv3_2 = tf.layers.conv3d(inputs=drop3_1,
                                       filters=4 * nb_filters,
                                       kernel_size=k_size,
                                       strides=(1, 1, 1),
                                       padding='SAME',
                                       activation=None,
                                       use_bias=True,
                                       kernel_initializer=tf.contrib.layers.xavier_initializer(),
                                       bias_initializer=tf.constant_initializer(0.0),
                                       kernel_regularizer=tf.nn.l2_loss)

            bn3_2 = tf.layers.batch_normalization(conv3_2, axis=-1, training=self.is_training)
            relu3_2 = tf.nn.relu(bn3_2)

            # shape = (patch/8, patch/8, patch/8)
            pool3_2 = tf.layers.max_pooling3d(inputs=relu3_2, pool_size=(2, 2, 2),
                                              strides=(2, 2, 2), padding='VALID')
            drop3_2 = tf.nn.dropout(pool3_2, self.dropout_placeholder)

            # print(conv.get_shape())

        with tf.variable_scope('predict'):
            print(drop3_2.get_shape())
            innerdim = np.prod(drop3_2.get_shape().as_list()[1:])
            print(innerdim)
            features = tf.reshape(drop3_2, [-1, innerdim])
            print(features.get_shape())

            self.score = tf.layers.dense(inputs=features,
                                         units=1,
                                         kernel_initializer=tf.contrib.layers.xavier_initializer())
            print(self.score.get_shape())

    def add_pred_op(self):
        probs = tf.sigmoid(self.score)

        self.pred = probs > .5

    def add_loss_op(self):
        ce_loss = tf.nn.sparse_softmax_cross_entropy_with_logits(logits=self.score, labels=self.mgmtmethylated)
        ce_loss = tf.reduce_mean(ce_loss)
        reg_loss = self.config.l2 * tf.losses.get_regularization_loss()

        self.loss = ce_loss + reg_loss

        # for tensorboard
        tf.summary.scalar("loss", self.loss)
