import pytest
from unittest.mock import patch, Mock
import psutil

def test_system_vitals_unauthorized(client):
    """Test system vitals without auth"""
    response = client.get("/dashboard/system/simple/vitals")
    assert response.status_code == 200  # This endpoint doesn't require auth

def test_system_vitals_endpoint(client):
    """Test simple system vitals"""
    with patch('main.psutil.cpu_percent') as mock_cpu, \
         patch('main.psutil.virtual_memory') as mock_mem, \
         patch('main.psutil.disk_usage') as mock_disk:
        
        mock_cpu.return_value = 25.5
        mock_mem.return_value = Mock(percent=65.0)
        mock_disk.return_value = Mock(percent=45.0)
        
        response = client.get("/dashboard/system/simple/vitals")
        assert response.status_code == 200
        data = response.json()
        assert "cpu_usage" in data
        assert "memory_usage" in data
        assert "disk_usage" in data

def test_system_processes_endpoint(client):
    """Test simple processes"""
    response = client.get("/dashboard/system/simple/processes")
    assert response.status_code == 200
    assert isinstance(response.json(), list)

def test_system_ports_endpoint(client):
    """Test simple ports"""
    response = client.get("/dashboard/system/simple/ports")
    assert response.status_code == 200
    assert isinstance(response.json(), list)

def test_system_report_endpoint(client):
    """Test simple system report"""
    response = client.get("/dashboard/system/simple/report")
    assert response.status_code == 200
    assert "hostname" in response.json()
    assert "os" in response.json()

def test_websocket_status_unauthorized(client):
    """Test WebSocket status without auth"""
    response = client.get("/dashboard/system/websocket-status")
    assert response.status_code == 401

def test_websocket_status(authenticated_client):
    """Test WebSocket status endpoint"""
    response = authenticated_client.get("/dashboard/system/websocket-status")
    assert response.status_code == 200
    data = response.json()
    assert "system_vitals" in data
    assert "notifications" in data
    assert "command_status" in data

def test_collect_system_vitals_data():
    """Test the system vitals data collection function"""
    from main import collect_system_vitals_data
    
    with patch('main.psutil.cpu_percent') as mock_cpu, \
         patch('main.psutil.virtual_memory') as mock_mem, \
         patch('main.psutil.disk_usage') as mock_disk, \
         patch('main.psutil.net_io_counters') as mock_net, \
         patch('main.psutil.boot_time') as mock_boot, \
         patch('main.psutil.pids') as mock_pids, \
         patch('main.platform.system') as mock_system, \
         patch('main.platform.release') as mock_release, \
         patch('main.psutil.sensors_battery') as mock_battery:
        
        # Setup mocks
        mock_cpu.return_value = 25.5
        mock_mem.return_value = Mock(percent=65.0, used=1000000000, total=2000000000)
        mock_disk.return_value = Mock(percent=45.0, free=50000000000, total=100000000000)
        mock_net.return_value = Mock(bytes_sent=1000000, bytes_recv=2000000)
        mock_boot.return_value = 1704067200  # 2024-01-01
        mock_pids.return_value = [1, 2, 3, 4, 5]
        mock_system.return_value = "Linux"
        mock_release.return_value = "5.15.0"
        
        battery_mock = Mock()
        battery_mock.percent = 85.0
        battery_mock.power_plugged = True
        mock_battery.return_value = battery_mock
        
        data = collect_system_vitals_data()
        
        assert "cpu" in data
        assert "memory" in data
        assert "disk" in data
        assert "network" in data
        assert "system" in data
        assert "platform" in data
        assert "battery" in data
        assert "timestamp" in data
        assert data["battery"]["percent"] == 85.0
        assert data["battery"]["charging"] == True

def test_system_cleanup_unauthorized(client):
    """Test system cleanup without auth"""
    response = client.post("/dashboard/system/cleanup")
    assert response.status_code == 401

def test_system_cleanup_mock(authenticated_client):
    """Test system cleanup with mock"""
    with patch('main.os.listdir') as mock_listdir, \
         patch('main.os.path.isfile') as mock_isfile, \
         patch('main.os.remove') as mock_remove, \
         patch('main.os.path.exists') as mock_exists, \
         patch('main.os.walk') as mock_walk:
        
        # Mock temp directory cleanup
        mock_listdir.return_value = ['temp1.txt', 'temp2.log']
        mock_isfile.return_value = True
        
        # Mock browser cache cleanup
        mock_exists.return_value = True
        mock_walk.return_value = [
            ('/cache', [], ['file1.tmp', 'file2.cache'])
        ]
        
        response = authenticated_client.post("/dashboard/system/cleanup")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "results" in data