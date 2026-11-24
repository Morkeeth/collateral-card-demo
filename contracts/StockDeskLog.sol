// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// Public spend record for the Stock Desk. Only the desk wallet can write.
/// The desk never trades: each entry records one spend decision and the paid price check behind it.
contract StockDeskLog {
    address public immutable desk;
    uint256 public count;

    // action: 1 ALLOW, 2 CUT, 3 REFUSE. Amounts in USD cents.
    event SpendDecision(
        uint256 indexed n,
        bytes32 indexed receipt,
        uint8 action,
        uint256 askedCents,
        uint256 allowedCents,
        bytes32 paymentTx,
        string reason
    );

    error NotDesk();
    error BadAction();

    constructor(address desk_) {
        desk = desk_;
    }

    function record(
        bytes32 receipt,
        uint8 action,
        uint256 askedCents,
        uint256 allowedCents,
        bytes32 paymentTx,
        string calldata reason
    ) external returns (uint256 n) {
        if (msg.sender != desk) revert NotDesk();
        if (action == 0 || action > 3) revert BadAction();
        n = ++count;
        emit SpendDecision(n, receipt, action, askedCents, allowedCents, paymentTx, reason);
    }
}
