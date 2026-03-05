"""
Neural network architectures:
  - LSTMModel: 3-layer LSTM with attention and dropout
  - TradingTransformer: Transformer encoder for sequence classification
Both output 3-class logits: [SELL, HOLD, BUY]
"""

from __future__ import annotations

import math
import torch
import torch.nn as nn
import torch.nn.functional as F


class Attention(nn.Module):
    def __init__(self, hidden_size: int) -> None:
        super().__init__()
        self.attn = nn.Linear(hidden_size, 1)

    def forward(self, lstm_out: torch.Tensor) -> torch.Tensor:
        # lstm_out: (batch, seq, hidden)
        scores = self.attn(lstm_out).squeeze(-1)           # (batch, seq)
        weights = F.softmax(scores, dim=-1).unsqueeze(-1)  # (batch, seq, 1)
        context = (lstm_out * weights).sum(dim=1)          # (batch, hidden)
        return context


class LSTMModel(nn.Module):
    """
    3-layer bidirectional LSTM with multi-head attention,
    layer normalisation, and residual connections.
    """

    def __init__(
        self,
        n_features: int,
        hidden_size: int = 256,
        n_layers: int = 3,
        dropout: float = 0.2,
        n_classes: int = 3,
    ) -> None:
        super().__init__()
        self.hidden_size = hidden_size
        self.n_layers = n_layers

        self.input_proj = nn.Linear(n_features, hidden_size)
        self.norm_in = nn.LayerNorm(hidden_size)

        self.lstm = nn.LSTM(
            input_size=hidden_size,
            hidden_size=hidden_size,
            num_layers=n_layers,
            batch_first=True,
            dropout=dropout if n_layers > 1 else 0.0,
            bidirectional=True,
        )
        self.attn = Attention(hidden_size * 2)
        self.norm = nn.LayerNorm(hidden_size * 2)
        self.dropout = nn.Dropout(dropout)
        self.fc1 = nn.Linear(hidden_size * 2, hidden_size)
        self.fc2 = nn.Linear(hidden_size, n_classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (batch, seq, features)
        x = F.gelu(self.norm_in(self.input_proj(x)))
        lstm_out, _ = self.lstm(x)
        context = self.attn(lstm_out)
        context = self.norm(context)
        out = self.dropout(F.gelu(self.fc1(context)))
        return self.fc2(out)


class PositionalEncoding(nn.Module):
    def __init__(self, d_model: int, max_len: int = 512, dropout: float = 0.1) -> None:
        super().__init__()
        self.dropout = nn.Dropout(dropout)
        pe = torch.zeros(max_len, d_model)
        position = torch.arange(max_len).unsqueeze(1).float()
        div = torch.exp(
            torch.arange(0, d_model, 2).float() * (-math.log(10000.0) / d_model)
        )
        pe[:, 0::2] = torch.sin(position * div)
        pe[:, 1::2] = torch.cos(position * div)
        self.register_buffer("pe", pe.unsqueeze(0))   # (1, max_len, d_model)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = x + self.pe[:, : x.size(1)]
        return self.dropout(x)


class TradingTransformer(nn.Module):
    """
    Transformer encoder for market regime classification.
    """

    def __init__(
        self,
        n_features: int,
        d_model: int = 256,
        nhead: int = 8,
        n_encoder_layers: int = 4,
        dim_feedforward: int = 1024,
        dropout: float = 0.1,
        n_classes: int = 3,
    ) -> None:
        super().__init__()
        self.input_proj = nn.Linear(n_features, d_model)
        self.pos_enc = PositionalEncoding(d_model, dropout=dropout)
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model, nhead=nhead,
            dim_feedforward=dim_feedforward,
            dropout=dropout, batch_first=True,
            norm_first=True,
        )
        self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=n_encoder_layers)
        self.pool = nn.AdaptiveAvgPool1d(1)
        self.classifier = nn.Sequential(
            nn.LayerNorm(d_model),
            nn.Linear(d_model, d_model // 2),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(d_model // 2, n_classes),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (batch, seq, features)
        x = self.pos_enc(self.input_proj(x))
        encoded = self.encoder(x)                       # (batch, seq, d_model)
        pooled = self.pool(encoded.transpose(1, 2)).squeeze(-1)  # (batch, d_model)
        return self.classifier(pooled)


def get_device() -> torch.device:
    """Return optimal device: MPS (Apple Silicon) > CUDA > CPU."""
    if torch.backends.mps.is_available():
        return torch.device("mps")
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")
