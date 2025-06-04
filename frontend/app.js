// Configuration
// Use backend container name when running in Docker, fallback to localhost for direct access
const API_BASE_URL = window.location.hostname === 'localhost' && window.location.port === '8080' 
    ? 'http://localhost:8000'  // Docker Compose setup
    : 'http://localhost:8000';  // Direct file access

console.log('API_BASE_URL:', API_BASE_URL);

// State management
let currentCredentials = null;
let currentBuckets = [];
let currentSnapshot = null;

// DOM Elements
const credentialsForm = document.getElementById('credentialsForm');
const credentialsCard = document.getElementById('credentialsCard');
const bucketsCard = document.getElementById('bucketsCard');
const bucketDetailsCard = document.getElementById('bucketDetailsCard');
const loadingIndicator = document.getElementById('loadingIndicator');
const errorAlert = document.getElementById('errorAlert');
const errorMessage = document.getElementById('errorMessage');
const bucketsList = document.getElementById('bucketsList');
const backToBuckets = document.getElementById('backToBuckets');

// Utility functions
function formatBytes(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

function formatDate(dateString) {
    const date = new Date(dateString);
    return date.toLocaleDateString() + ' ' + date.toLocaleTimeString();
}

function showError(message) {
    errorMessage.textContent = message;
    errorAlert.style.display = 'flex';
    setTimeout(() => {
        errorAlert.style.display = 'none';
    }, 5000);
}

function showLoading() {
    loadingIndicator.style.display = 'block';
}

function hideLoading() {
    loadingIndicator.style.display = 'none';
}

// Password visibility toggle
document.querySelectorAll('.toggle-password').forEach(button => {
    button.addEventListener('click', () => {
        const targetId = button.getAttribute('data-target');
        const input = document.getElementById(targetId);
        if (input.type === 'password') {
            input.type = 'text';
            button.textContent = '👁️‍🗨️';
        } else {
            input.type = 'password';
            button.textContent = '👁️';
        }
    });
});

// Form submission handler
credentialsForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    console.log('Form submitted');
    
    // Get form data
    const formData = new FormData(credentialsForm);
    currentCredentials = {
        access_key: formData.get('accessKey'),
        secret_key: formData.get('secretKey'),
        region: formData.get('region') || 'default',
        endpoint_url: formData.get('endpoint')
    };
    
    console.log('Credentials:', { ...currentCredentials, secret_key: '***' });
    
    // Validate endpoint URL
    try {
        new URL(currentCredentials.endpoint_url);
    } catch (err) {
        showError('Please enter a valid endpoint URL');
        return;
    }
    
    await discoverBuckets();
});

// Discover buckets with enhanced data collection
async function discoverBuckets() {
    console.log('Starting bucket discovery...');
    showLoading();
    errorAlert.style.display = 'none';
    
    try {
        const response = await fetch(`${API_BASE_URL}/discover/buckets`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(currentCredentials)
        });
        
        console.log('Buckets response:', response.status);
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to discover buckets');
        }
        
        currentBuckets = await response.json();
        console.log('Found buckets:', currentBuckets.length);
        
        // Enhance bucket data with file details
        let totalSize = 0;
        let totalFiles = 0;
        
        for (let bucket of currentBuckets) {
            try {
                console.log(`Getting details for bucket: ${bucket.name}`);
                const detailsResponse = await fetch(`${API_BASE_URL}/discover/bucket/${bucket.name}`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify(currentCredentials)
                });
                
                console.log(`Details response for ${bucket.name}:`, detailsResponse.status);
                
                if (detailsResponse.ok) {
                    const details = await detailsResponse.json();
                    bucket.files = details.files || [];
                    bucket.file_count = details.file_count || 0;
                    bucket.total_size = details.total_size || 0;
                    bucket.versioning_status = details.versioning_status || 'Unknown';
                    totalSize += details.total_size || 0;
                    totalFiles += details.file_count || 0;
                    console.log(`Bucket ${bucket.name}: ${details.file_count} files, ${details.total_size} bytes`);
                } else {
                    const errorText = await detailsResponse.text();
                    console.error(`Failed response for bucket ${bucket.name}:`, errorText);
                    bucket.files = [];
                    bucket.file_count = 0;
                    bucket.total_size = 0;
                }
            } catch (err) {
                console.error(`Failed to get details for bucket ${bucket.name}:`, err);
                bucket.files = [];
                bucket.file_count = 0;
                bucket.total_size = 0;
            }
        }
        
        // Create snapshot data
        currentSnapshot = {
            id: '',  // Will be assigned by backend
            timestamp: new Date().toISOString(),
            endpoint: currentCredentials.endpoint_url,
            region: currentCredentials.region,
            buckets: currentBuckets,
            total_size: totalSize,
            total_files: totalFiles
        };
        
        console.log('Created snapshot:', currentSnapshot);
        
        // Always save snapshot even if some bucket details failed
        try {
            await saveSnapshotToBackend(currentSnapshot);
        } catch (snapErr) {
            console.error('Failed to save snapshot:', snapErr);
        }
        
        displayBuckets();
        
    } catch (error) {
        console.error('Discovery error:', error);
        showError(error.message);
    } finally {
        hideLoading();
    }
}

// Save snapshot to backend
async function saveSnapshotToBackend(snapshot) {
    console.log('Saving snapshot to backend...');
    try {
        const response = await fetch(`${API_BASE_URL}/snapshot/save`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(snapshot)
        });
        
        console.log('Snapshot save response:', response.status);
        
        if (!response.ok) {
            const errorText = await response.text();
            console.error('Snapshot save error:', errorText);
            throw new Error('Failed to save snapshot');
        }
        
        const savedMetadata = await response.json();
        console.log('Snapshot saved:', savedMetadata);
        
        // Show snapshot info
        showSnapshotInfo(savedMetadata);
        
    } catch (error) {
        console.error('Error saving snapshot:', error);
    }
}

// Show snapshot info
function showSnapshotInfo(metadata) {
    const infoDiv = document.createElement('div');
    infoDiv.className = 'snapshot-info';
    infoDiv.innerHTML = `
        <div class="alert alert-success">
            <span class="alert-icon">✅</span>
            <div>
                <strong>Snapshot Saved Successfully!</strong>
                <p>ID: ${metadata.id}</p>
                <p>File: ${metadata.filename}</p>
            </div>
        </div>
    `;
    
    bucketsCard.insertBefore(infoDiv, bucketsCard.firstChild);
    
    // Remove after 5 seconds
    setTimeout(() => {
        infoDiv.remove();
    }, 5000);
}

// Display buckets
function displayBuckets() {
    console.log('Displaying buckets...');
    credentialsCard.style.display = 'none';
    bucketDetailsCard.style.display = 'none';
    bucketsCard.style.display = 'block';
    
    // Display snapshot summary
    if (currentSnapshot) {
        const summaryDiv = document.getElementById('snapshotSummary') || createSnapshotSummaryDiv();
        summaryDiv.innerHTML = `
            <h3>Discovery Summary</h3>
            <div class="summary-stats">
                <div class="stat">
                    <span class="stat-label">Endpoint</span>
                    <span class="stat-value">${currentSnapshot.endpoint}</span>
                </div>
                <div class="stat">
                    <span class="stat-label">Total Buckets</span>
                    <span class="stat-value">${currentSnapshot.buckets.length}</span>
                </div>
                <div class="stat">
                    <span class="stat-label">Total Files</span>
                    <span class="stat-value">${currentSnapshot.total_files.toLocaleString()}</span>
                </div>
                <div class="stat">
                    <span class="stat-label">Total Size</span>
                    <span class="stat-value">${formatBytes(currentSnapshot.total_size)}</span>
                </div>
            </div>
            <div class="json-preview">
                <h4>Snapshot Preview</h4>
                <pre>${JSON.stringify(currentSnapshot, null, 2)}</pre>
            </div>
        `;
        
        if (!document.getElementById('snapshotSummary')) {
            bucketsCard.insertBefore(summaryDiv, document.getElementById('bucketsList'));
        }
    }
    
    bucketsList.innerHTML = '';
    
    if (currentBuckets.length === 0) {
        bucketsList.innerHTML = '<p style="text-align: center; color: #6c757d;">No buckets found</p>';
        return;
    }
    
    currentBuckets.forEach(bucket => {
        const bucketElement = document.createElement('div');
        bucketElement.className = 'bucket-item';
        bucketElement.onclick = () => viewBucketDetails(bucket.name);
        
        bucketElement.innerHTML = `
            <div class="bucket-name">🪣 ${bucket.name}</div>
            <div class="bucket-date">Created: ${bucket.creation_date ? formatDate(bucket.creation_date) : 'Unknown'}</div>
            <div class="bucket-stats-mini">
                <span>Files: ${bucket.file_count || 0}</span>
                <span>Size: ${formatBytes(bucket.total_size || 0)}</span>
                <span>Versioning: ${bucket.versioning_status || 'Unknown'}</span>
            </div>
        `;
        
        bucketsList.appendChild(bucketElement);
    });
}

// Create snapshot summary div
function createSnapshotSummaryDiv() {
    const div = document.createElement('div');
    div.id = 'snapshotSummary';
    div.className = 'snapshot-summary';
    return div;
}

// View bucket details
async function viewBucketDetails(bucketName) {
    // First check if we have cached data
    const cachedBucket = currentBuckets.find(b => b.name === bucketName);
    if (cachedBucket && cachedBucket.files) {
        displayBucketDetails({
            name: bucketName,
            files: cachedBucket.files,
            file_count: cachedBucket.file_count,
            total_size: cachedBucket.total_size
        });
        return;
    }
    
    // Otherwise fetch from API
    showLoading();
    errorAlert.style.display = 'none';
    
    try {
        const response = await fetch(`${API_BASE_URL}/discover/bucket/${bucketName}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(currentCredentials)
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to get bucket details');
        }
        
        const bucketDetails = await response.json();
        displayBucketDetails(bucketDetails);
        
    } catch (error) {
        showError(error.message);
    } finally {
        hideLoading();
    }
}

// Display bucket details
function displayBucketDetails(details) {
    bucketsCard.style.display = 'none';
    bucketDetailsCard.style.display = 'block';
    
    document.getElementById('bucketName').textContent = `🪣 ${details.name}`;
    document.getElementById('fileCount').textContent = details.file_count.toLocaleString();
    document.getElementById('totalSize').textContent = formatBytes(details.total_size);
    
    const tbody = document.getElementById('filesTableBody');
    tbody.innerHTML = '';
    
    if (details.files.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" style="text-align: center; color: #6c757d;">No files in this bucket</td></tr>';
        return;
    }
    
    details.files.forEach(file => {
        const row = document.createElement('tr');
        row.innerHTML = `
            <td class="file-name">${file.key}</td>
            <td class="file-size">${formatBytes(file.size)}</td>
            <td>${formatDate(file.last_modified)}</td>
            <td style="font-family: monospace; font-size: 0.9em;">${file.etag}</td>
        `;
        tbody.appendChild(row);
    });
}

// Back to buckets button
backToBuckets.addEventListener('click', () => {
    bucketDetailsCard.style.display = 'none';
    bucketsCard.style.display = 'block';
});

// Allow going back to credentials form
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        if (bucketDetailsCard.style.display === 'block') {
            bucketDetailsCard.style.display = 'none';
            bucketsCard.style.display = 'block';
        } else if (bucketsCard.style.display === 'block') {
            bucketsCard.style.display = 'none';
            credentialsCard.style.display = 'block';
        }
    }
});

// Set default endpoint for common S3 providers
document.getElementById('endpoint').addEventListener('focus', function() {
    if (!this.value) {
        this.value = 'https://s3c.tns.cx';
    }
}); 