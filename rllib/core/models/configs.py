from dataclasses import dataclass, field
from typing import List, Callable, Dict, Union, Tuple
from ray.rllib.utils.typing import ViewRequirementsDict
import functools

import gymnasium as gym

from ray.rllib.core.models.base import ModelConfig, Model, Encoder
from ray.rllib.utils.annotations import ExperimentalAPI


@ExperimentalAPI
def _framework_implemented(torch: bool = True, tf2: bool = True):
    """Decorator to check if a model was implemented in a framework.

    Args:
        torch: Whether we can build this model with torch.
        tf2: Whether we can build this model with tf2.

    Returns:
        The decorated function.

    Raises:
        ValueError: If the framework is not available to build.
    """
    accepted = []
    if torch:
        accepted.append("torch")
    if tf2:
        accepted.append("tf")
        accepted.append("tf2")

    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def checked_build(self, framework, **kwargs):
            if framework not in accepted:
                raise ValueError(
                    f"This config does not support framework "
                    f"{framework}. Only frameworks in {accepted} are "
                    f"supported."
                )
            return fn(self, framework, **kwargs)

        return checked_build

    return decorator


def _convert_to_lower_case_if_tf(string: str, framework: str) -> str:
    """Converts a string to lower case if the framework is torch.

    TensorFlow has lower-case names for activation functions, while PyTorch has
    camel-case names.

    Args:
        string: The string to convert.
        framework: The framework to check.

    Returns:
        The converted string.
    """
    if framework != "torch" and string is not None:
        return string.lower()
    return string


@ExperimentalAPI
@dataclass
class MLPHeadConfig(ModelConfig):
    """Configuration for a fully connected network.

    The configured MLP encodes 1D-observations into a latent space.
    The stack of layers is composed of a sequence of linear layers. The first layer
    has `input_dim` inputs and the last layer has `output_dim` outputs. The number of
    units inbetween is determined by `hidden_layer_dims`. If `hidden_layer_dims` is
    None, there is only one linear layer with `input_dim` inputs and `output_dim`
    outputs. Each layer is followed by an activation function as per this config.
    See ModelConfig for usage details.

    Example:

        Configuration:
        input_dim = 4
        hidden_layer_dims = [8, 8]
        hidden_layer_activation = "relu"
        output_dim = 2
        output_activation = "linear"

        Resulting stack in pseudocode:
        Linear(4, 8)
        ReLU()
        Linear(8, 8)
        ReLU()
        Linear(8, 2)

    Attributes:
        input_dim: The input dimension of the network. It cannot be None.
        hidden_layer_dims: The sizes of the hidden layers.
        hidden_layer_activation: The activation function to use after each layer (
            except for the output).
        output_activation: The activation function to use for the output layer.
        output_dim: The output dimension of the network.
    """

    input_dim: int = None
    hidden_layer_dims: List[int] = field(default_factory=lambda: [256, 256])
    hidden_layer_activation: str = "relu"
    output_activation: str = "linear"
    output_dim: int = None

    @_framework_implemented()
    def build(self, framework: str = "torch") -> Model:
        self.input_dim = int(self.input_dim)
        self.output_dim = int(self.output_dim)

        # Activation functions in TF are lower case
        self.output_activation = _convert_to_lower_case_if_tf(
            self.output_activation, framework
        )
        self.hidden_layer_activation = _convert_to_lower_case_if_tf(
            self.hidden_layer_activation, framework
        )

        if framework == "torch":
            from ray.rllib.core.models.torch.mlp import TorchMLPHead

            return TorchMLPHead(self)
        else:
            from ray.rllib.core.models.tf.mlp import TfMLPHead

            return TfMLPHead(self)


@ExperimentalAPI
@dataclass
class CNNEncoderConfig(ModelConfig):
    """Configuration for a convolutional network.

    The configured CNN encodes 3D-observations into a latent space.
    The stack of layers is composed of a sequence of convolutional layers.
    `input_dims` describes the shape of the input tensor. Beyond that, each layer
    specified by `filter_specifiers` is followed by an activation function according
    to `filter_activation`. The `output_dim` is reached by flattening a final
    convolutional layer and applying a linear layer with `output_activation`.
    See ModelConfig for usage details.

    Example:

        Configuration:
        input_dims = [84, 84, 3]
        filter_specifiers = [
            [16, [8, 8], 4],
            [32, [4, 4], 2],
        ]
        filter_activation = "relu"
        output_dim = 256
        output_activation = "linear"

        Resulting stack in pseudocode:
        Conv2D(in_channels=3, out_channels=16, kernel_size=[8, 8], stride=[4, 4])
        ReLU()
        Conv2D(in_channels=16, out_channels=32, kernel_size=[4, 4], stride=[2, 2])
        ReLU()
        Conv2D(in_channels=32, out_channels=1, kernel_size=[1, 1], stride=[1, 1])
        Flatten()
        Linear(121, 256)

    Attributes:
        input_dims: The input dimension of the network. These must be given in the
            form of `(width, height, channels)`.
        filter_specifiers: A list of lists, where each element of an inner list
            contains elements of the form
            `[number of channels/filters, [kernel width, kernel height], stride]` to
            specify a convolutional layer stacked in order of the outer list.
        filter_layer_activation: The activation function to use after each layer (
            except for the output).
        output_activation: The activation function to use for the output layer.
        output_dim: The output dimension. We append a final convolutional layer
            depth-only filters that is flattened and a final linear layer to achieve
            this dimension regardless of the previous filters.
    """

    input_dims: Union[List[int], Tuple[int]] = None
    filter_specifiers: List[List[Union[int, List[int]]]] = field(
        default_factory=lambda: [[16, [4, 4], 2], [32, [4, 4], 2], [64, [8, 8], 2]]
    )
    filter_layer_activation: str = "relu"
    output_activation: str = "linear"
    output_dim: int = None

    @_framework_implemented(tf2=False)
    def build(self, framework: str = "torch") -> Model:
        # Activation functions in TF are lower case
        self.output_activation = _convert_to_lower_case_if_tf(
            self.output_activation, framework
        )
        self.filter_layer_activation = _convert_to_lower_case_if_tf(
            self.filter_layer_activation, framework
        )

        if framework == "torch":
            from ray.rllib.core.models.torch.encoder import TorchCNNEncoder

            return TorchCNNEncoder(self)


@ExperimentalAPI
@dataclass
class MLPEncoderConfig(MLPHeadConfig):
    """Configuration for an MLP that acts as an encoder.

    Although it inherits from MLPHeadConfig, it does not output an MLPHead.
    This inheritance is solely to unify the configuration options between MLPEncoders
    and MLPHeads.

    See ModelConfig for usage details.
    """

    @_framework_implemented()
    def build(self, framework: str = "torch") -> Encoder:
        # Activation functions in TF are lower case
        self.output_activation = _convert_to_lower_case_if_tf(
            self.output_activation, framework
        )
        self.hidden_layer_activation = _convert_to_lower_case_if_tf(
            self.hidden_layer_activation, framework
        )

        if framework == "torch":
            from ray.rllib.core.models.torch.encoder import TorchMLPEncoder

            return TorchMLPEncoder(self)
        else:
            from ray.rllib.core.models.tf.encoder import TfMLPEncoder

            return TfMLPEncoder(self)


@ExperimentalAPI
@dataclass
class LSTMEncoderConfig(ModelConfig):
    """Configuration for a LSTM encoder.

    See ModelConfig for usage details.

    Attributes:
        input_dim: The input dimension of the network. It cannot be None.
        hidden_dim: The size of the hidden layer.
        num_layers: The number of LSTM layers.
        batch_first: Wether the input is batch first or not.
        output_activation: The activation function to use for the output layer.
        observation_space: The observation space of the environment.
        action_space: The action space of the environment.
        view_requirements_dict: The view requirements to use if anything else than
            observation_space or action_space is to be encoded. This signifies an
            advanced use case.
        get_tokenizer_config: A callable that takes a gym.Space and a dict and
            returns a ModelConfig to build tokenizers for observations, actions and
            other spaces that might be present in the view_requirements_dict.

    """

    input_dim: int = None
    hidden_dim: int = None
    num_layers: int = None
    batch_first: bool = True
    output_activation: str = "linear"
    observation_space: gym.Space = None
    action_space: gym.Space = None
    view_requirements_dict: ViewRequirementsDict = None
    get_tokenizer_config: Callable[[gym.Space, Dict], ModelConfig] = None
    output_dim: int = None

    @_framework_implemented(tf2=False)
    def build(self, framework: str = "torch") -> Encoder:
        self.input_dim = int(self.input_dim)
        if framework == "torch":
            from ray.rllib.core.models.torch.encoder import TorchLSTMEncoder

            return TorchLSTMEncoder(self)


@ExperimentalAPI
@dataclass
class ActorCriticEncoderConfig(ModelConfig):
    """Configuration for an ActorCriticEncoder.

    The base encoder functions like other encoders in RLlib. It is wrapped by the
    ActorCriticEncoder to provides a shared encoder Model to use in RLModules that
    provides twofold outputs: one for the actor and one for the critic. See
    ModelConfig for usage details.

    Attributes:
        base_encoder_config: The configuration for the wrapped encoder(s).
        shared: Whether the base encoder is shared between the actor and critic.
    """

    base_encoder_config: ModelConfig = None
    shared: bool = True

    @_framework_implemented()
    def build(self, framework: str = "torch") -> Model:
        if framework == "torch":
            from ray.rllib.core.models.torch.encoder import (
                TorchActorCriticEncoder,
            )

            return TorchActorCriticEncoder(self)
        else:
            from ray.rllib.core.models.tf.encoder import TfActorCriticEncoder

            return TfActorCriticEncoder(self)
