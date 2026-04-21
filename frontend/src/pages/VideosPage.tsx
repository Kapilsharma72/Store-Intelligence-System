import VideoLibrary from '../components/VideoLibrary'
import UploadZone from '../components/UploadZone'

export default function VideosPage() {
  return (
    <>
      <div className="col-span-full">
        <h1 className="text-2xl font-bold mb-4">Video Management</h1>
        <p className="text-gray-600 dark:text-gray-400 mb-6">
          Upload CCTV footage and manage your video library. Process videos to extract analytics.
        </p>
      </div>

      {/* Upload Section */}
      <div className="col-span-full">
        <UploadZone />
      </div>

      {/* Video Library */}
      <div className="col-span-full mt-6">
        <VideoLibrary />
      </div>
    </>
  )
}
