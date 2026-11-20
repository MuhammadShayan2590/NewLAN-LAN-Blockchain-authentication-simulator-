// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

contract DeviceAuth {
    address public admin;
    mapping(string => bool) private authorizedDevices;

    // Events let the dashboard list devices (a mapping cannot be enumerated)
    event DeviceRegistered(string macAddress);
    event DeviceRevoked(string macAddress);

    modifier onlyAdmin() {
        require(msg.sender == admin, "Only admin can perform this action");
        _;
    }

    constructor() {
        admin = msg.sender;
    }

    function registerDevice(string memory _macAddress) public onlyAdmin {
        authorizedDevices[_macAddress] = true;
        emit DeviceRegistered(_macAddress);
    }

    function revokeDevice(string memory _macAddress) public onlyAdmin {
        authorizedDevices[_macAddress] = false;
        emit DeviceRevoked(_macAddress);
    }

    function isDeviceAuthorized(string memory _macAddress) public view returns (bool) {
        return authorizedDevices[_macAddress];
    }
}
