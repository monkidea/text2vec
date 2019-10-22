from text2vec.models import InputFeeder
from text2vec.models.components.utils import sequence_cost
import tensorflow as tf

tf.enable_eager_execution()


class EncodingModel(tf.keras.Model):

    def __init__(self, feeder, encoder, decoder):
        super(EncodingModel, self).__init__()
        assert isinstance(feeder, InputFeeder)
        assert isinstance(encoder, tf.keras.layers.Layer)
        assert isinstance(decoder, tf.keras.layers.Layer)

        self.embed_layer = feeder
        self.encode_layer = encoder
        self.decode_layer = decoder

        self.num_labels = feeder.num_labels

    def process_inputs(self, tokens, encoding=True):
        assert isinstance(tokens, tf.RaggedTensor)

        if encoding:
            x, mask, _ = self.embed_layer(tokens, max_sequence_length=self.encode_layer.max_sequence_length)
            return x, mask

        batch_size = tokens.nrows()
        bos = tf.fill([batch_size], value='<s>')
        bos = tf.expand_dims(bos, axis=-1)
        eos = tf.fill([batch_size], value='</s>')
        eos = tf.expand_dims(eos, axis=-1)

        target = tf.concat([tokens, eos], axis=1)
        target = tf.ragged.map_flat_values(self.embed_layer.table.lookup, target)
        target = target[:, :self.decode_layer.max_sequence_length]

        dec_tokens = tf.concat([bos, tokens], axis=-1)
        x, mask, time_steps = self.embed_layer(dec_tokens, max_sequence_length=self.decode_layer.max_sequence_length)
        return x, mask, time_steps, target

    def cost(self, logits, targets, smoothing=False):
        return sequence_cost(
            target_sequences=targets,
            sequence_logits=logits,
            num_labels=self.num_labels,
            smoothing=smoothing
        )

    def forward(self, sentences):
        tokens = tf.compat.v2.strings.split(sentences, sep=' ')
        x_enc, enc_mask = self.process_inputs(tokens)
        # x_enc, context = self.encode_layer((x_enc, enc_mask), training=True)
        return x_enc, enc_mask

    def call(self, sentences, **kwargs):
        # turn sentences into ragged tensors of tokens
        tokens = tf.compat.v2.strings.split(sentences, sep=' ')
        # tokens = tf.RaggedTensor.from_sparse(tokens)

        # turn incoming sentences into relevant tensor batches
        x_enc, enc_mask = self.process_inputs(tokens)
        x_dec, dec_mask, dec_time_steps, targets = self.process_inputs(tokens, encoding=False)

        # encoding/decoding pipelines
        x_enc, context = self.encode_layer((x_enc, enc_mask), training=True)
        x_out = self.decode_layer((
            x_enc,
            enc_mask,
            x_dec,
            dec_mask,
            context,
            self.encode_layer.attention,
            self.embed_layer.embeddings
        ))
        x_out = x_out[:, :dec_time_steps]
        targets = targets.to_tensor(default_value=0)
        return self.cost(logits=x_out, targets=targets)


@tf.function
def train_step(sentences, model, optimizer):
    assert isinstance(model, EncodingModel)
    assert isinstance(optimizer, tf.keras.optimizers.Optimizer)

    if tf.executing_eagerly():
        with tf.GradientTape() as tape:
            loss = model(sentences)
        gradients = tape.gradient(loss, model.trainable_variables)
    else:
        loss = model(sentences)
        gradients = tf.gradients(loss, model.trainable_variables)

    optimizer.apply_gradients(zip(gradients, model.trainable_variables))
    return loss, gradients


@tf.function
def get_token_embeddings(sentences, model):
    assert isinstance(model, EncodingModel)
    tokens = tf.compat.v2.strings.split(sentences, sep=' ')
    return model.process_inputs(tokens)


@tf.function
def get_context_embeddings(sentences, model):
    assert isinstance(model, EncodingModel)
    tokens = tf.compat.v2.strings.split(sentences, sep=' ')
    return model.encode_layer(model.process_inputs(tokens), training=False)