import React, { useRef, useEffect, useState, useCallback } from 'react';
import mapboxgl from 'mapbox-gl';
import 'mapbox-gl/dist/mapbox-gl.css';
import './LocationPicker.css';

const MAPBOX_TOKEN = import.meta.env.VITE_MAPBOX_TOKEN;
// Mapbox GL in the browser requires a *public* token (pk.*). Secret tokens (sk.*) must not be used in frontend code.
const MAPBOX_TOKEN_IS_PUBLIC =
  typeof MAPBOX_TOKEN === 'string' && MAPBOX_TOKEN.trim().startsWith('pk.');

const LocationPicker = ({ value, onChange }) => {
  const mapContainer = useRef(null);
  const map = useRef(null);
  const marker = useRef(null);
  const [locating, setLocating] = useState(false);
  const [address, setAddress] = useState('');

  // Reverse geocode to get a readable address
  const reverseGeocode = useCallback(async (lng, lat) => {
    if (!MAPBOX_TOKEN_IS_PUBLIC) return;
    try {
      const res = await fetch(
        `https://api.mapbox.com/geocoding/v5/mapbox.places/${lng},${lat}.json?access_token=${MAPBOX_TOKEN}&limit=1`
      );
      const data = await res.json();
      const place = data.features?.[0]?.place_name || '';
      setAddress(place);
    } catch {
      setAddress(`${lat.toFixed(4)}, ${lng.toFixed(4)}`);
    }
  }, []);

  // Place or move the marker (skip redundant onChange to avoid update loops)
  const setMarker = useCallback((lng, lat) => {
    if (!map.current) return;
    const newCoords = { lat, lng };
    const same =
      value &&
      Math.abs(value.lat - lat) < 1e-6 &&
      Math.abs(value.lng - lng) < 1e-6;
    if (!same) onChange(newCoords);

    if (marker.current) {
      marker.current.setLngLat([lng, lat]);
    } else {
      marker.current = new mapboxgl.Marker({ color: '#667eea', draggable: true })
        .setLngLat([lng, lat])
        .addTo(map.current);

      marker.current.on('dragend', () => {
        const lngLat = marker.current.getLngLat();
        onChange({ lat: lngLat.lat, lng: lngLat.lng });
        reverseGeocode(lngLat.lng, lngLat.lat);
      });
    }

    reverseGeocode(lng, lat);
  }, [onChange, reverseGeocode, value]);

  // Initialize map (only with a public pk.* token)
  useEffect(() => {
    if (!MAPBOX_TOKEN_IS_PUBLIC || map.current) return;

    mapboxgl.accessToken = MAPBOX_TOKEN;

    map.current = new mapboxgl.Map({
      container: mapContainer.current,
      style: 'mapbox://styles/mapbox/streets-v12',
      center: value ? [value.lng, value.lat] : [-98.5795, 39.8283], // Default: center of US
      zoom: value ? 13 : 3.5,
    });

    map.current.addControl(new mapboxgl.NavigationControl(), 'top-right');

    // Click to pick location
    map.current.on('click', (e) => {
      setMarker(e.lngLat.lng, e.lngLat.lat);
    });

    // If we already have a value, place the marker
    if (value) {
      // Wait for map to load before placing marker
      map.current.on('load', () => {
        setMarker(value.lng, value.lat);
      });
    }

    return () => {
      if (map.current) {
        map.current.remove();
        map.current = null;
        marker.current = null;
      }
    };
  }, []);  // eslint-disable-line react-hooks/exhaustive-deps

  // Use current location via browser geolocation
  const handleUseCurrentLocation = () => {
    if (!navigator.geolocation) {
      alert('Geolocation is not supported by your browser.');
      return;
    }

    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      (position) => {
        const { latitude, longitude } = position.coords;
        setMarker(longitude, latitude);
        if (map.current) {
          map.current.flyTo({ center: [longitude, latitude], zoom: 13, duration: 1500 });
        }
        setLocating(false);
      },
      (err) => {
        console.error('Geolocation error:', err);
        alert('Could not get your location. Please pick it on the map.');
        setLocating(false);
      },
      { enableHighAccuracy: true, timeout: 10000 }
    );
  };

  if (!MAPBOX_TOKEN) {
    return (
      <div className="location-picker">
        <label className="input-label">Your Location</label>
        <div className="location-missing-token">
          Set <code>VITE_MAPBOX_TOKEN</code> in your <code>.env</code> to enable the map.
        </div>
      </div>
    );
  }

  if (!MAPBOX_TOKEN_IS_PUBLIC) {
    return (
      <div className="location-picker">
        <label className="input-label">Your Location</label>
        <div className="location-missing-token">
          Use a <strong>public</strong> Mapbox token (<code>pk.*</code>), not a secret token (<code>sk.*</code>).
          Get a public token at{' '}
          <a href="https://account.mapbox.com/access-tokens/" target="_blank" rel="noopener noreferrer">
            account.mapbox.com
          </a>
          .
        </div>
      </div>
    );
  }

  return (
    <div className="location-picker">
      <label className="input-label">Your Location</label>

      <div className="location-actions">
        <button
          type="button"
          className="current-location-btn"
          onClick={handleUseCurrentLocation}
          disabled={locating}
        >
          {locating ? (
            <>
              <span className="location-spinner" />
              Locating...
            </>
          ) : (
            <>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="3" />
                <path d="M12 2v4M12 18v4M2 12h4M18 12h4" />
              </svg>
              Use Current Location
            </>
          )}
        </button>

        {value && address && (
          <span className="location-address" title={address}>
            {address}
          </span>
        )}
      </div>

      <div className="map-wrapper">
        <div ref={mapContainer} className="map-container" />
        {!value && (
          <div className="map-overlay">
            Click on the map to pick your location
          </div>
        )}
      </div>
    </div>
  );
};

export default LocationPicker;
