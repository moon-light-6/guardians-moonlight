import unittest
from unittest.mock import patch

import numpy as np
import torch
from torch import nn

from scripts.A2C import a2c_update, parse_args


class TinyActorCritic(nn.Module):
    def __init__(self):
        super().__init__()
        self.actor = nn.Linear(2, 3)
        self.critic = nn.Linear(2, 1)

    def forward(self, obs):
        return self.actor(obs), self.critic(obs).squeeze(-1)


class TestA2C(unittest.TestCase):
    def test_defaults_are_separate_from_ppo(self):
        args = parse_args([])
        self.assertEqual(args.total_timesteps, 100000)
        self.assertTrue(args.output_dir.endswith('a2c_pgh'))

    def test_single_update_uses_log_policy_gradient_and_mask(self):
        torch.manual_seed(7)
        model = TinyActorCritic()
        optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
        batch = {'obs': np.array([[1.,0.],[0.,1.],[1.,1.]], dtype=np.float32),
                 'masks': np.array([[True,True,False]]*3), 'actions': np.array([0,1,0])}
        advantages = np.array([2.,-1.,.5], dtype=np.float32)
        returns = np.array([1.,-.5,.2], dtype=np.float32)
        with torch.no_grad():
            logits, values = model(torch.tensor(batch['obs']))
            dist = torch.distributions.Categorical(logits=logits.masked_fill(~torch.tensor(batch['masks']), -1e9))
            adv = torch.tensor(advantages)
            adv = (adv - adv.mean()) / (adv.std(unbiased=False) + 1e-8)
            expected_actor = -(dist.log_prob(torch.tensor(batch['actions']))*adv).mean().item()
            expected_critic = ((torch.tensor(returns)-values)**2).mean().item()
            expected_entropy = dist.entropy().mean().item()
        old = {k:v.clone() for k,v in model.state_dict().items()}
        with patch.object(optimizer, 'step', wraps=optimizer.step) as step:
            stats = a2c_update(model, optimizer, batch, advantages, returns,
                               value_coef=.5, entropy_coef=.01, max_grad_norm=.5)
        self.assertEqual(step.call_count, 1)
        self.assertAlmostEqual(stats['actor_loss'], expected_actor, places=6)
        self.assertAlmostEqual(stats['critic_loss'], expected_critic, places=6)
        self.assertAlmostEqual(stats['entropy'], expected_entropy, places=6)
        self.assertAlmostEqual(stats['total_loss'], expected_actor+.5*expected_critic-.01*expected_entropy, places=6)
        self.assertTrue(any(not torch.equal(v, old[k]) for k,v in model.state_dict().items()))

    def test_single_sample_is_finite(self):
        model = TinyActorCritic()
        optimizer = torch.optim.Adam(model.parameters())
        stats = a2c_update(model, optimizer,
                           {'obs': [[1.,0.]], 'masks': [[True,False,False]], 'actions': [0]},
                           [1.], [2.], value_coef=.5, entropy_coef=.01, max_grad_norm=.5)
        self.assertTrue(all(np.isfinite(v) for v in stats.values()))


if __name__ == '__main__':
    unittest.main()
