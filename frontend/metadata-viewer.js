// Metadata viewer functionality
let currentMetadata = null;
let snapshots = [];

// Tab switching
function showTab(tabName) {
    // Hide all tabs
    document.querySelectorAll('.tab-content').forEach(tab => {
        tab.style.display = 'none';
    });
    
    // Remove active class from all buttons
    document.querySelectorAll('.tab-button').forEach(btn => {
        btn.classList.remove('active');
    });
    
    // Show selected tab
    if (tabName === 'discover') {
        document.getElementById('discoverTab').style.display = 'block';
        document.querySelector('.tab-button:nth-child(1)').classList.add('active');
    } else if (tabName === 'metadata') {
        document.getElementById('metadataTab').style.display = 'block';
        document.querySelector('.tab-button:nth-child(2)').classList.add('active');
        refreshMetadata();
    }
}

// Refresh metadata list
async function refreshMetadata() {
    try {
        const response = await fetch(`${API_BASE_URL}/snapshot/list`);
        if (!response.ok) {
            throw new Error('Failed to load snapshots');
        }
        
        snapshots = await response.json();
        displayMetadataList(snapshots);
    } catch (error) {
        console.error('Failed to load snapshots:', error);
        showError('Failed to load snapshots from server');
    }
}

// Display metadata list
function displayMetadataList(snapshots) {
    const metadataList = document.getElementById('metadataList');
    
    if (snapshots.length === 0) {
        metadataList.innerHTML = `
            <div class="empty-state">
                <p>No snapshots saved yet.</p>
                <p>Use the Discover tab to scan S3 endpoints.</p>
            </div>
        `;
        return;
    }
    
    metadataList.innerHTML = snapshots.map(snapshot => `
        <div class="metadata-item" onclick="viewMetadataDetail('${snapshot.id}')">
            <div class="metadata-item-header">
                <span class="metadata-endpoint">📍 ${snapshot.endpoint}</span>
                <span class="metadata-timestamp">${formatDate(snapshot.timestamp)}</span>
            </div>
            <div class="metadata-item-stats">
                <span>🪣 ${snapshot.bucket_count} buckets</span>
                <span>📄 ${snapshot.total_files.toLocaleString()} files</span>
                <span>💾 ${formatBytes(snapshot.total_size)}</span>
            </div>
            <div class="metadata-item-footer">
                <small>📁 ${snapshot.filename}</small>
            </div>
        </div>
    `).join('');
}

// View metadata detail
async function viewMetadataDetail(id) {
    try {
        const response = await fetch(`${API_BASE_URL}/snapshot/${id}`);
        if (!response.ok) {
            throw new Error('Failed to load snapshot details');
        }
        
        currentMetadata = await response.json();
        displayMetadataDetail(currentMetadata);
    } catch (error) {
        console.error('Failed to load snapshot:', error);
        showError('Failed to load snapshot details');
    }
}

// Display metadata detail
function displayMetadataDetail(metadata) {
    document.querySelector('.card:has(#metadataList)').style.display = 'none';
    document.getElementById('metadataDetailCard').style.display = 'block';
    
    document.getElementById('metadataTimestamp').textContent = formatDate(metadata.timestamp);
    document.getElementById('metadataEndpoint').textContent = metadata.endpoint;
    document.getElementById('metadataRegion').textContent = metadata.region;
    document.getElementById('metadataBucketCount').textContent = metadata.buckets.length;
    document.getElementById('metadataTotalFiles').textContent = metadata.total_files.toLocaleString();
    document.getElementById('metadataTotalSize').textContent = formatBytes(metadata.total_size);
    
    // Format JSON for display
    const formattedJson = JSON.stringify(metadata, null, 2);
    document.getElementById('metadataJson').textContent = formattedJson;
}

// Back to metadata list
function backToMetadataList() {
    document.getElementById('metadataDetailCard').style.display = 'none';
    document.querySelector('.card:has(#metadataList)').style.display = 'block';
    currentMetadata = null;
}

// Export current metadata
function exportCurrentMetadata() {
    if (!currentMetadata) return;
    
    const dataStr = JSON.stringify(currentMetadata, null, 2);
    const dataUri = 'data:application/json;charset=utf-8,'+ encodeURIComponent(dataStr);
    
    const exportFileDefaultName = `s3-discovery-${currentMetadata.endpoint.replace(/[^a-z0-9]/gi, '-')}-${new Date(currentMetadata.timestamp).getTime()}.json`;
    
    const linkElement = document.createElement('a');
    linkElement.setAttribute('href', dataUri);
    linkElement.setAttribute('download', exportFileDefaultName);
    linkElement.click();
}

// Delete specific snapshot
async function deleteSnapshot(id) {
    if (!confirm('Are you sure you want to delete this snapshot?')) {
        return;
    }
    
    try {
        const response = await fetch(`${API_BASE_URL}/snapshot/${id}`, {
            method: 'DELETE'
        });
        
        if (!response.ok) {
            throw new Error('Failed to delete snapshot');
        }
        
        // Refresh the list
        await refreshMetadata();
        
    } catch (error) {
        console.error('Failed to delete snapshot:', error);
        showError('Failed to delete snapshot');
    }
}

// Delete current snapshot
async function deleteCurrentSnapshot() {
    if (currentMetadata && currentMetadata.id) {
        await deleteSnapshot(currentMetadata.id);
        backToMetadataList();
    }
}

// Clear all discoveries (not available with backend storage)
async function clearAllDiscoveries() {
    alert('To delete snapshots, please delete them individually or contact the administrator.');
}

// Enhanced discovery with version support
async function discoverBucketVersions(bucketName) {
    try {
        const response = await fetch(`${API_BASE_URL}/discover/bucket/${bucketName}/versions`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(currentCredentials)
        });
        
        if (response.ok) {
            return await response.json();
        }
    } catch (error) {
        console.error('Version discovery not supported:', error);
    }
    return null;
} 