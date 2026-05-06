"""LSTM autoencoder for AKS metric reconstruction.

Trained on NORMAL windows only. The reconstruction error on the last 10
timesteps is the anomaly score.
"""

from __future__ import annotations

import torch
from torch import nn

from ml.constants import N_CHANNELS, WINDOW_SIZE

LATENT_DIM = 32
HIDDEN_DIM = 64
TAIL_STEPS = 10


class LSTMAutoencoder(nn.Module):
    def __init__(
        self,
        n_channels: int = N_CHANNELS,
        window_size: int = WINDOW_SIZE,
        hidden_dim: int = HIDDEN_DIM,
        latent_dim: int = LATENT_DIM,
    ) -> None:
        super().__init__()
        self.window_size = window_size
        self.n_channels = n_channels

        self.encoder_l1 = nn.LSTM(n_channels, hidden_dim, batch_first=True)
        self.encoder_l2 = nn.LSTM(hidden_dim, latent_dim, batch_first=True)

        self.decoder_l1 = nn.LSTM(latent_dim, hidden_dim, batch_first=True)
        self.decoder_l2 = nn.LSTM(hidden_dim, n_channels, batch_first=True)
        self.output = nn.Linear(n_channels, n_channels)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        h, _ = self.encoder_l1(x)
        _, (latent, _) = self.encoder_l2(h)
        latent = latent.squeeze(0)

        repeated = latent.unsqueeze(1).repeat(1, self.window_size, 1)

        h, _ = self.decoder_l1(repeated)
        h, _ = self.decoder_l2(h)
        return self.output(h)


def reconstruction_error(
    model: LSTMAutoencoder,
    x: torch.Tensor,
    per_channel: bool = False,
) -> torch.Tensor:
    """Mean squared error on the last TAIL_STEPS timesteps.

    Returns a tensor of shape (batch,) by default, or (batch, n_channels)
    when per_channel=True.
    """
    model.eval()
    with torch.no_grad():
        recon = model(x)
        diff = (recon[:, -TAIL_STEPS:, :] - x[:, -TAIL_STEPS:, :]) ** 2
    if per_channel:
        return diff.mean(dim=1)
    return diff.mean(dim=(1, 2))
