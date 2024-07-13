# Copyright 2020 Tsinghua SPMI Lab / Tasi
# Apache 2.0.
# Author: Xiangzhu (kongxiangzhu99@gmail.com), Keyu An
#
# Acknowledgment:
# This code is adapted from the ESPnet project. The original code can be found at https://github.com/espnet/espnet.
#
# Description:
#   This script defines the Stft class for performing Short-Time Fourier Transform (STFT) and its inverse.
#   It also provides various utility functions related to tensor manipulation and masking.
#

from distutils.version import LooseVersion
from typing import Optional
from typing import Tuple
from typing import Union

import torch
from torch_complex.tensor import ComplexTensor
from typeguard import check_argument_types

from .nets_utils import make_pad_mask
from abc import ABC
from abc import abstractmethod
from typing import Tuple

import torch

class InversibleInterface(ABC):
    """
    An abstract base class that defines an interface for classes that have an inverse method.
    """
    @abstractmethod
    def inverse(
        self, input: torch.Tensor, input_lengths: torch.Tensor = None
    ) -> Tuple[torch.Tensor, torch.Tensor]:
        # return output, output_lengths
        raise NotImplementedError


class Stft(torch.nn.Module, InversibleInterface):
    """
    A class for performing Short-Time Fourier Transform (STFT) and its inverse.

    Methods:
        forward(input: torch.Tensor, ilens: torch.Tensor = None) -> Tuple[torch.Tensor, Optional[torch.Tensor]]:
            Applies STFT to the input tensor.

        inverse(input: Union[torch.Tensor, ComplexTensor], ilens: torch.Tensor = None) -> Tuple[torch.Tensor, Optional[torch.Tensor]]:
            Applies inverse STFT to the input tensor.
    """
    def __init__(
        self,
        n_fft: int = 512,
        win_length: int = None,
        hop_length: int = 128,
        window: Optional[str] = "hann",
        center: bool = True,
        normalized: bool = False,
        onesided: bool = True,
    ):
        assert check_argument_types()
        super().__init__()
        self.n_fft = n_fft
        if win_length is None:
            self.win_length = n_fft
        else:
            self.win_length = win_length
        self.hop_length = hop_length
        self.center = center
        self.normalized = normalized
        self.onesided = onesided
        if window is not None and not hasattr(torch, f"{window}_window"):
            raise ValueError(f"{window} window is not implemented")
        self.window = window

    def extra_repr(self):
        return (
            f"n_fft={self.n_fft}, "
            f"win_length={self.win_length}, "
            f"hop_length={self.hop_length}, "
            f"center={self.center}, "
            f"normalized={self.normalized}, "
            f"onesided={self.onesided}"
        )

    def forward(
        self, input: torch.Tensor, ilens: torch.Tensor = None
    ) -> Tuple[torch.Tensor, Optional[torch.Tensor]]:
        """STFT forward function.
        Args:
            input: (Batch, Nsamples) or (Batch, Nsample, Channels)
            ilens: (Batch)
        Returns:
            output: (Batch, Frames, Freq, 2) or (Batch, Frames, Channels, Freq, 2)
        """
        bs = input.size(0)
        if input.dim() == 3:
            multi_channel = True
            # input: (Batch, Nsample, Channels) -> (Batch * Channels, Nsample)
            input = input.transpose(1, 2).reshape(-1, input.size(1))
        else:
            multi_channel = False

        # NOTE(kamo):
        #   The default behaviour of torch.stft is compatible with librosa.stft
        #   about padding and scaling.
        #   Note that it's different from scipy.signal.stft

        # output: (Batch, Freq, Frames, 2=real_imag)
        # or (Batch, Channel, Freq, Frames, 2=real_imag)
        if self.window is not None:
            window_func = getattr(torch, f"{self.window}_window")
            window = window_func(
                self.win_length, dtype=input.dtype, device=input.device
            )
        else:
            window = None
        #print("begin stft")
        output = torch.stft(
            input,
            n_fft=self.n_fft,
            win_length=self.win_length,
            hop_length=self.hop_length,
            center=self.center,
            window=window,
            normalized=self.normalized,
            onesided=self.onesided,
            return_complex=False,
        )
        # print("end stft")
        # output: (Batch, Freq, Frames, 2=real_imag)
        # -> (Batch, Frames, Freq, 2=real_imag)
        output = output.transpose(1, 2)
        if multi_channel:
            # output: (Batch * Channel, Frames, Freq, 2=real_imag)
            # -> (Batch, Frame, Channel, Freq, 2=real_imag)
            output = output.view(bs, -1, output.size(1), output.size(2), 2).transpose(
                1, 2
            )

        if ilens is not None:
            if self.center:
                pad = self.win_length // 2
                ilens = ilens + 2 * pad

            olens = (ilens - self.win_length) // self.hop_length + 1
            output.masked_fill_(make_pad_mask(olens, output, 1), 0.0)
        else:
            olens = None

        return output, olens

    def inverse(
        self, input: Union[torch.Tensor, ComplexTensor], ilens: torch.Tensor = None
    ) -> Tuple[torch.Tensor, Optional[torch.Tensor]]:
        """Inverse STFT.
        :param input: Tensor (batch, T, F, 2) or ComplexTensor (batch, T, F)
        :param ilens:
        :return:
        """
        if LooseVersion(torch.__version__) >= LooseVersion("1.6.0"):
            istft = torch.functional.istft
        else:
            try:
                import torchaudio
            except ImportError:
                raise ImportError(
                    "Please install torchaudio>=0.3.0 or use torch>=1.6.0"
                )

            if not hasattr(torchaudio.functional, "istft"):
                raise ImportError(
                    "Please install torchaudio>=0.3.0 or use torch>=1.6.0"
                )
            istft = torchaudio.functional.istft

        if isinstance(input, ComplexTensor):
            input = torch.stack([input.real, input.imag], dim=-1)
        assert input.shape[-1] == 2
        input = input.transpose(1, 2)

        wavs = istft(
            input,
            n_fft=self.n_fft,
            hop_length=self.hop_length,
            win_length=self.win_length,
            center=self.center,
            normalized=self.normalized,
            onesided=self.onesided,
            length=ilens.max() if ilens is not None else ilens,
        )

        return wavs, ilens



