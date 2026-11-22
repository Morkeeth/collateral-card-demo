// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @dev Stand-in Chainlink feed: decimals 8, settable latestAnswer, latestRoundData.updatedAt = now.
contract SettableFeed {
    uint8 public constant decimals = 8;
    int256 private _answer;

    function setAnswer(int256 answer) external {
        _answer = answer;
    }

    function latestAnswer() external view returns (int256) {
        return _answer;
    }

    function latestRoundData()
        external
        view
        returns (uint80 roundId, int256 answer, uint256 startedAt, uint256 updatedAt, uint80 answeredInRound)
    {
        return (1, _answer, block.timestamp, block.timestamp, 1);
    }
}
