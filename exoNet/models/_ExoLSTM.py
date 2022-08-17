import os

import keras
import numpy as np
from keras.callbacks import EarlyStopping, ReduceLROnPlateau
from keras.layers import Input, Dense, BatchNormalization, Dropout, LSTM
from keras.layers.advanced_activations import ReLU
from keras.models import Model, load_model
from keras.optimizers import Nadam
from keras.utils import to_categorical

from exoNet.models._losses import METRICS, LOSSES
from exoNet.models._network import Network
from exoNet.utils import train_test_split_data, label_encoder


class ExoLSTM(Network):
    def __init__(self, seq_len, n_channels, n_classes=2, **kwargs):
        super().__init__()
        self.seq_len = seq_len
        self.n_channels = n_channels
        self.n_classes = n_classes
        self.model_name = ExoLSTM.__name__

        self.lr = kwargs.get("learning_rate", 0.001)
        self.dr_rate = kwargs.get("dropout_rate", 0.2)
        self.model_path = kwargs.get("model_path", "./models/FCN/")
        self.loss_fn = kwargs.get("loss_fn", 'cce')
        self.lambda_l1 = kwargs.get('lambda_l1', 0.0)
        self.lambda_l2 = kwargs.get('lambda_l2', 0.0)
        self.use_batchnorm = kwargs.get("use_batchnorm", False)

        self.sequence = Input(shape=(self.seq_len, self.n_channels,), name="data")

        self.network_kwargs = {
            "seq_len": self.seq_len,
            "n_channels": self.n_channels,
            "n_classes": self.n_classes,
            "dropout_rate": self.dr_rate,
            "loss_fn": self.loss_fn,
            "use_batchnorm": self.use_batchnorm,
        }

        self.training_kwargs = {
            "learning_rate": self.lr,
            "model_path": self.model_path,
            "lambda_l1": self.lambda_l1,
            "lambda_l2": self.lambda_l2,
        }

        self.init_w = keras.initializers.glorot_normal()
        self.regularizer = keras.regularizers.l1_l2(self.lambda_l1, self.lambda_l2)
        self._create_network()
        self._compile_models()

        print_summary = kwargs.get("print_summary", True)

        if print_summary:
            self.model.summary()

    def _create_network(self):
        h = LSTM(64, activation='tanh', return_sequences=True, kernel_initializer=self.init_w, kernel_regularizer=self.regularizer)(
            self.sequence)

        h = LSTM(32, activation='tanh', return_sequences=False, kernel_initializer=self.init_w, kernel_regularizer=self.regularizer)(
            h)

        h = Dense(16, kernel_initializer=self.init_w, kernel_regularizer=self.regularizer, use_bias=False)(h)
        if self.use_batchnorm:
            h = BatchNormalization()(h)
        h = ReLU()(h)
        if self.dr_rate > 0:
            h = Dropout(self.dr_rate)(h)

        output = Dense(self.n_classes, kernel_initializer=self.init_w, kernel_regularizer=self.regularizer,
                       activation='softmax')(h)

        self.model = Model(inputs=self.sequence, outputs=output)

    def _compile_models(self):
        self.optimizer = Nadam(lr=self.lr)
        self.model.compile(optimizer=self.optimizer, loss=LOSSES[self.loss_fn],
                           metrics=['acc', METRICS['sensitivity'], METRICS['specificity']])

    def to_latent(self):
        latent_model = Model(self.model.input, self.model.layers[-2].output)
        return latent_model.predict(data)

    def predict(self, data):
        return self.label_encoder.inverse_transform(np.argmax(self.model.predict(data), axis=1))

    def save_model(self):
        os.makedirs(self.model_path, exist_ok=True)
        self.model.save(os.path.join(self.model_path, f"{self.model_name}.h5"), overwrite=True)

    def save_model_weights(self):
        os.makedirs(self.model_path, exist_ok=True)
        self.model.save(os.path.join(self.model_path, f"weights.h5"), overwrite=True)
    
    def restore_model_weights(self):
        self.model.load_weights(os.path.join(self.model_path, f"weights.h5"))
        self._compile_models()

    def restore_model(self):
        self.model = load_model(os.path.join(self.model_path, f"{self.model_name}.h5"), compile=False)
        self._compile_models()

    def train(self, seq_data, labels, le=None, n_epochs=500, batch_size=32, early_stopping_kwargs={},
              lr_reducer_kwargs={}, verbose=2):
        x_train, x_valid, y_train, y_valid = train_test_split_data(seq_data, labels, 0.80, stratify=True)

        y_train, self.label_encoder = label_encoder(y_train, label_encoder=le)
        y_train = to_categorical(y_train, num_classes=self.n_classes)

        y_valid, self.label_encoder = label_encoder(y_valid, label_encoder=le)
        y_valid = to_categorical(y_valid, num_classes=self.n_classes)

        callbacks = []

        if early_stopping_kwargs != {}:
            callbacks.append(EarlyStopping(**early_stopping_kwargs))

        if lr_reducer_kwargs != {}:
            callbacks.append(ReduceLROnPlateau(**lr_reducer_kwargs))

        self.model.fit(x=x_train,
                       y=y_train,
                       validation_data=(x_valid, y_valid),
                       epochs=n_epochs,
                       batch_size=batch_size,
                       verbose=verbose,
                       callbacks=callbacks,
                       )