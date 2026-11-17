# Copyright 2026 Kamkar Foundation, LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Every rule a sheet can be judged by, by name. A published rule is never changed or removed: a new rule gets a
new name, so every sheet ever published can be judged again under its own rule."""

from agoranome_inspector import rule, rule2, rule_mpp

RULES = {rule.RULE: rule.judge, rule2.RULE: rule2.judge, rule_mpp.RULE: rule_mpp.judge}
METHODS = {rule.RULE: rule.METHOD, rule2.RULE: rule2.METHOD, rule_mpp.RULE: rule_mpp.METHOD}

# The rule a new x402 sheet is judged by. Sheet-1 judged price in each asset's own units; sheet-2 judges it on
# dollar options only (rule2.py). Sheets published under sheet-1 keep it, and can be restated (restate.py).
CURRENT = rule2.RULE
